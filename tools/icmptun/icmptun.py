#!/usr/bin/env python3
"""icmptun — a reliable stream tunnel carried inside ICMP echo packets.

This is a transport of last resort for networks that pass ICMP (ping) but block
or throttle normal TCP/UDP. It carries no cryptography of its own: the client
exposes a local TCP port and forwards it, over ICMP, to a TCP target on the
server (meant to be a local Xray inbound). All authentication and encryption
stay in Xray; icmptun only moves bytes.

  server:  icmptun server --target 127.0.0.1:8443 [--key SECRET]
  client:  icmptun client --server <node-ip> --listen 127.0.0.1:1080 [--key SECRET]

Wire format (ICMP echo payload):

  MAGIC(4) ver(1) flags(1) session(2) seq(4) ack(4) win(2) dlen(2) data(dlen)

flags bit0 = direction (0 = client→server, 1 = server→client), bit1 = FIN (the
sender has closed its half of the stream). The client sends
echo *requests* (type 8) and the server sends echo *replies* (type 0); each side
ignores packets carrying its own direction bit, so the kernel's automatic echo
reply (which reflects the client's payload verbatim, direction bit still 0) is
dropped by the client. Reliability (sequence numbers, cumulative acks, timed
retransmission and reordering) is layered on top because ICMP is lossy and
unordered. A keyed check rejects stray or spoofed packets cheaply.

Needs CAP_NET_RAW (root, or setcap cap_net_raw). Linux only.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import logging
import os
import select
import socket
import struct
import sys
import threading
import time
from dataclasses import dataclass, field

MAGIC = b"ic1\x00"
VERSION = 1
FLAG_FIN = 0x02
_FIN = object()  # in-process sentinel: an ordered end-of-stream marker
HEADER = struct.Struct("!4sBBHIIHH")  # magic, ver, flags, session, seq, ack, win, dlen
HDR_LEN = HEADER.size
MAX_DATA = 1024          # payload bytes per packet; keeps total well under any MTU
WINDOW = 64              # in-flight packets per direction
RTO = 0.30               # retransmit timeout (seconds)
MAX_RETRIES = 20
IDLE_POLL = 0.05         # client keepalive/poll interval when idle (NAT keepalive)
SESSION_TIMEOUT = 60.0
KEY_LEN = 8

log = logging.getLogger("icmptun")


def _checksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def _tag(key: bytes, body: bytes) -> bytes:
    return hmac.new(key, body, hashlib.sha256).digest()[:KEY_LEN] if key else b"\x00" * KEY_LEN


def build_frame(key: bytes, direction: int, session: int, seq: int, ack: int, win: int, data: bytes, fin: bool = False) -> bytes:
    flags = (direction & 1) | (FLAG_FIN if fin else 0)
    body = HEADER.pack(MAGIC, VERSION, flags, session, seq & 0xFFFFFFFF, ack & 0xFFFFFFFF, win, len(data)) + data
    return body + _tag(key, body)


def parse_frame(key: bytes, buf: bytes) -> dict | None:
    if len(buf) < HDR_LEN + KEY_LEN:
        return None
    body, tag = buf[:-KEY_LEN], buf[-KEY_LEN:]
    magic, ver, flags, session, seq, ack, win, dlen = HEADER.unpack(body[:HDR_LEN])
    if magic != MAGIC or ver != VERSION or dlen > MAX_DATA or len(body) < HDR_LEN + dlen:
        return None
    body = body[: HDR_LEN + dlen]
    if not hmac.compare_digest(tag[:KEY_LEN], _tag(key, body)):
        return None
    return {"dir": flags & 1, "fin": bool(flags & FLAG_FIN), "session": session, "seq": seq, "ack": ack, "win": win, "data": body[HDR_LEN : HDR_LEN + dlen]}


def icmp_packet(icmp_type: int, ident: int, seq: int, payload: bytes) -> bytes:
    head = struct.pack("!BBHHH", icmp_type, 0, 0, ident & 0xFFFF, seq & 0xFFFF)
    chk = _checksum(head + payload)
    return struct.pack("!BBHHH", icmp_type, 0, chk, ident & 0xFFFF, seq & 0xFFFF) + payload


def icmp_strip(raw: bytes) -> tuple[int, bytes] | None:
    """(icmp_type, icmp_payload) from a packet read on a raw ICMP socket (incl. IP header)."""
    if len(raw) < 20:
        return None
    ihl = (raw[0] & 0x0F) * 4
    icmp = raw[ihl:]
    if len(icmp) < 8:
        return None
    return icmp[0], icmp[8:]


# --------------------------------------------------------------------------- reliable stream
@dataclass
class Stream:
    """A reliable, ordered byte stream over unreliable datagrams (one per session)."""

    send_seq: int = 0
    send_una: int = 0                                   # oldest unacked seq
    unacked: dict = field(default_factory=dict)         # seq -> (sent_at, tries, data|_FIN)
    peer_win: int = WINDOW
    recv_next: int = 0
    recv_buf: dict = field(default_factory=dict)        # seq -> bytes | _FIN
    sent_fin: bool = False
    closed: bool = False
    last_rx: float = field(default_factory=time.monotonic)

    def can_send(self) -> bool:
        return len(self.unacked) < min(WINDOW, max(1, self.peer_win))

    def queue(self, data) -> int:
        seq = self.send_seq
        self.unacked[seq] = (0.0, 0, data)              # sent_at 0 => send now
        self.send_seq = (self.send_seq + 1) & 0xFFFFFFFF
        return seq

    def queue_fin(self) -> None:
        if not self.sent_fin:
            self.sent_fin = True
            self.queue(_FIN)

    def on_ack(self, ack: int, win: int) -> None:
        self.peer_win = win
        for seq in list(self.unacked):
            if _lt(seq, ack):
                del self.unacked[seq]
        self.send_una = ack

    def accept(self, seq: int, content) -> list:
        """Store an incoming segment (bytes or _FIN); return in-order items now deliverable."""
        if _lt(seq, self.recv_next) or len(self.recv_buf) > WINDOW * 2:
            return []
        self.recv_buf.setdefault(seq, content)
        out = []
        while self.recv_next in self.recv_buf:
            out.append(self.recv_buf.pop(self.recv_next))
            self.recv_next = (self.recv_next + 1) & 0xFFFFFFFF
        return out

    def due(self, now: float) -> list:
        ready = []
        for seq, (sent_at, tries, data) in sorted(self.unacked.items(), key=lambda kv: kv[1][0]):
            if now - sent_at >= (RTO if sent_at else 0):
                if tries >= MAX_RETRIES:
                    self.closed = True
                    continue
                self.unacked[seq] = (now, tries + 1, data)
                ready.append((seq, data))
        return ready


def _lt(a: int, b: int) -> bool:
    """Serial (wrap-around) comparison: is a < b in 32-bit sequence space?"""
    return ((a - b) & 0xFFFFFFFF) > 0x80000000


# --------------------------------------------------------------------------- shared endpoint
class Endpoint:
    def __init__(self, key: bytes, is_server: bool):
        self.key = key
        self.is_server = is_server
        self.send_dir = 1 if is_server else 0          # server sends s2c(1), client sends c2s(0)
        self.recv_dir = 0 if is_server else 1
        self.icmp_type = 0 if is_server else 8          # server: echo reply, client: echo request
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1 << 20)
        self._icmp_seq = 0
        self.lock = threading.Lock()

    def send(self, addr: str, session: int, seq: int, ack: int, win: int, data: bytes, fin: bool = False) -> None:
        frame = build_frame(self.key, self.send_dir, session, seq, ack, win, data, fin)
        self._icmp_seq = (self._icmp_seq + 1) & 0xFFFF
        pkt = icmp_packet(self.icmp_type, session, self._icmp_seq, frame)
        try:
            self.sock.sendto(pkt, (addr, 0))
        except OSError as e:
            log.debug("send failed: %s", e)

    def recv(self, timeout: float):
        r, _, _ = select.select([self.sock], [], [], timeout)
        if not r:
            return None
        try:
            raw, addr = self.sock.recvfrom(65535)
        except OSError:
            return None
        stripped = icmp_strip(raw)
        if not stripped:
            return None
        _, payload = stripped
        frame = parse_frame(self.key, payload)
        if frame is None or frame["dir"] != self.recv_dir:
            return None                                 # not ours / our own reflection / kernel echo
        frame["addr"] = addr[0]
        return frame


# --------------------------------------------------------------------------- server
class Server:
    def __init__(self, target: tuple[str, int], key: bytes):
        self.target = target
        self.ep = Endpoint(key, is_server=True)
        self.sessions: dict[int, "ServerSession"] = {}

    def run(self) -> None:
        log.info("icmptun server: forwarding ICMP → %s:%d", *self.target)
        last_tick = time.monotonic()
        while True:
            frame = self.ep.recv(0.02)
            now = time.monotonic()
            if frame:
                self._on_frame(frame, now)
            if now - last_tick >= 0.02:
                self._tick(now)
                last_tick = now

    def _on_frame(self, frame, now) -> None:
        sid = frame["session"]
        sess = self.sessions.get(sid)
        if sess is None:
            sess = ServerSession(sid, frame["addr"], self.ep, self.target)
            if not sess.connect():
                return
            self.sessions[sid] = sess
            log.info("session %d from %s", sid, frame["addr"])
        sess.peer = frame["addr"]
        sess.handle(frame, now)

    def _tick(self, now) -> None:
        for sid, sess in list(self.sessions.items()):
            sess.pump(now)
            if sess.dead(now):
                sess.close()
                del self.sessions[sid]
                log.info("session %d closed", sid)


class _SessionBase:
    """Common pump/handle logic for one TCP connection tunnelled over one ICMP session."""

    def __init__(self, sid: int, peer: str, ep: Endpoint):
        self.sid = sid
        self.peer = peer
        self.ep = ep
        self.stream = Stream()
        self.stream.last_rx = time.monotonic()
        self.tcp: socket.socket | None = None
        self.tcp_eof = False
        self.pending_ack = True

    def handle(self, frame, now) -> None:
        self.stream.last_rx = now
        self.stream.on_ack(frame["ack"], frame["win"])
        if frame["data"] or frame["fin"]:
            content = _FIN if frame["fin"] else frame["data"]
            for chunk in self.stream.accept(frame["seq"], content):
                if chunk is _FIN:
                    self.tcp_eof = True
                    if self.tcp:
                        try:
                            self.tcp.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass
                elif self.tcp:
                    try:
                        self.tcp.sendall(chunk)
                    except OSError:
                        self.stream.closed = True
            self.pending_ack = True

    def pump(self, now) -> None:
        # Pull bytes from the local TCP side into the send buffer.
        if self.tcp and not self.stream.closed:
            while self.stream.can_send():
                try:
                    r, _, _ = select.select([self.tcp], [], [], 0)
                    if not r:
                        break
                    data = self.tcp.recv(MAX_DATA)
                except OSError:
                    self.stream.closed = True
                    break
                if data == b"":
                    self.stream.queue_fin()
                    self.tcp = None
                    break
                self.stream.queue(data)
        # (Re)transmit anything due.
        sent = False
        for seq, data in self.stream.due(now):
            self._emit(seq, data)
            sent = True
        if self.pending_ack and not sent:
            self._emit_ack()
        self.pending_ack = False

    def _emit(self, seq: int, data) -> None:
        if data is _FIN:
            self.ep.send(self.peer, self.sid, seq, self.stream.recv_next, self._win(), b"", fin=True)
        else:
            self.ep.send(self.peer, self.sid, seq, self.stream.recv_next, self._win(), data)

    def _emit_ack(self) -> None:
        self.ep.send(self.peer, self.sid, self.stream.send_seq, self.stream.recv_next, self._win(), b"")

    def _win(self) -> int:
        return max(1, WINDOW - len(self.stream.recv_buf))

    def dead(self, now) -> bool:
        clean = self.stream.sent_fin and self.tcp_eof and not self.stream.unacked and not self.stream.recv_buf
        return clean or (self.stream.closed and not self.stream.unacked) or (now - self.stream.last_rx > SESSION_TIMEOUT)

    def close(self) -> None:
        if self.tcp:
            try:
                self.tcp.close()
            except OSError:
                pass
            self.tcp = None


class ServerSession(_SessionBase):
    def __init__(self, sid, peer, ep, target):
        super().__init__(sid, peer, ep)
        self.target = target

    def connect(self) -> bool:
        try:
            self.tcp = socket.create_connection(self.target, timeout=5)
            self.tcp.setblocking(False)
            return True
        except OSError as e:
            log.warning("session %d: cannot reach target %s:%d: %s", self.sid, *self.target, e)
            return False


# --------------------------------------------------------------------------- client
class Client:
    def __init__(self, server_ip: str, listen: tuple[str, int], key: bytes):
        self.server_ip = server_ip
        self.listen = listen
        self.ep = Endpoint(key, is_server=False)
        self.sessions: dict[int, ClientSession] = {}
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(listen)
        self.listener.listen(128)
        self.listener.setblocking(False)

    def run(self) -> None:
        log.info("icmptun client: %s:%d → ICMP → %s", self.listen[0], self.listen[1], self.server_ip)
        last_tick = time.monotonic()
        while True:
            self._accept()
            frame = self.ep.recv(0.01)
            now = time.monotonic()
            if frame and frame["session"] in self.sessions:
                self.sessions[frame["session"]].handle(frame, now)
            if now - last_tick >= IDLE_POLL:
                for sid, sess in list(self.sessions.items()):
                    sess.pump(now)
                    if sess.dead(now):
                        sess.close()
                        del self.sessions[sid]
                last_tick = now

    def _accept(self) -> None:
        try:
            conn, _ = self.listener.accept()
        except (BlockingIOError, OSError):
            return
        conn.setblocking(False)
        sid = self._new_sid()
        self.sessions[sid] = ClientSession(sid, self.server_ip, self.ep, conn)
        log.info("local connection → session %d", sid)

    def _new_sid(self) -> int:
        while True:
            sid = struct.unpack("!H", os.urandom(2))[0]
            if sid and sid not in self.sessions:
                return sid


class ClientSession(_SessionBase):
    def __init__(self, sid, peer, ep, conn):
        super().__init__(sid, peer, ep)
        self.tcp = conn

    def pump(self, now) -> None:
        super().pump(now)
        # The client must keep sending (echo requests) so the server's replies
        # can traverse NAT, even with nothing to say.
        if not self.stream.unacked and not self.pending_ack:
            self._emit_ack()


# --------------------------------------------------------------------------- cli
def _hostport(s: str) -> tuple[str, int]:
    host, _, port = s.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"expected host:port, got {s!r}")
    return host, int(port)


def _key(args) -> bytes:
    secret = args.key or os.environ.get("ICMPTUN_KEY", "")
    return hashlib.sha256(secret.encode()).digest() if secret else b""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Reliable tunnel over ICMP echo (ping).")
    p.add_argument("--log-level", default="info")
    p.add_argument("--key", default="", help="shared secret (or ICMPTUN_KEY env)")
    sub = p.add_subparsers(dest="mode", required=True)
    s = sub.add_parser("server", help="run on the node")
    s.add_argument("--target", type=_hostport, required=True, help="local TCP target, e.g. 127.0.0.1:8443")
    c = sub.add_parser("client", help="run on the user's machine (Linux)")
    c.add_argument("--server", required=True, help="node IP address")
    c.add_argument("--listen", type=_hostport, default=("127.0.0.1", 1080), help="local TCP listen address")
    args = p.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    key = _key(args)
    try:
        if args.mode == "server":
            Server(args.target, key).run()
        else:
            Client(args.server, args.listen, key).run()
    except PermissionError:
        print("icmptun needs raw sockets: run as root or `setcap cap_net_raw+ep $(command -v python3)`", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
