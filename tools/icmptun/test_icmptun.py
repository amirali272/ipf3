"""Logic tests for icmptun: framing and the reliable-stream engine. No root needed."""

import os
import random
import sys

sys.path.insert(0, os.path.dirname(__file__))

import icmptun as it  # noqa: E402


# --------------------------------------------------------------------------- framing
def test_frame_roundtrip():
    key = b"k" * 32
    f = it.build_frame(key, direction=1, session=0x1234, seq=5, ack=9, win=40, data=b"hello", fin=False)
    p = it.parse_frame(key, f)
    assert p == {"dir": 1, "fin": False, "session": 0x1234, "seq": 5, "ack": 9, "win": 40, "data": b"hello"}


def test_frame_fin_and_direction_bits():
    key = b""
    f = it.build_frame(key, direction=0, session=7, seq=1, ack=1, win=1, data=b"", fin=True)
    p = it.parse_frame(key, f)
    assert p["fin"] is True and p["dir"] == 0 and p["data"] == b""


def test_bad_key_or_magic_rejected():
    f = it.build_frame(b"right" * 7, 0, 1, 0, 0, 1, b"x")
    assert it.parse_frame(b"wrong" * 7, f) is None
    assert it.parse_frame(b"right" * 7, f[:-1] + bytes([f[-1] ^ 1])) is None  # tampered tag
    assert it.parse_frame(b"right" * 7, b"\x00" * 40) is None                 # wrong magic


def test_icmp_wrap_strip():
    pkt = it.icmp_packet(8, 0xABCD, 3, b"payload")
    # simulate an IP header (20 bytes) prepended as the kernel delivers it
    ip = bytes([0x45]) + b"\x00" * 19
    typ, payload = it.icmp_strip(ip + pkt)
    assert typ == 8 and payload == b"payload"


# --------------------------------------------------------------------------- serial arithmetic
def test_serial_less_than_wraps():
    assert it._lt(1, 2)
    assert not it._lt(2, 1)
    assert it._lt(0xFFFFFFF0, 0x00000005)   # wrap-around
    assert not it._lt(5, 5)


# --------------------------------------------------------------------------- reliable stream
def _deliver(src: it.Stream, dst: it.Stream, drop=0.0, dup=0.0, reorder=False, rng=None, now=0.0):
    """Move everything due on src into dst, optionally losing/duplicating/reordering."""
    rng = rng or random.Random(0)
    segs = src.due(now)
    if reorder:
        rng.shuffle(segs)
    out = []
    for seq, data in segs:
        copies = 1 + (1 if rng.random() < dup else 0)
        for _ in range(copies):
            if rng.random() < drop:
                continue
            content = it._FIN if data is it._FIN else data
            out += dst.accept(seq, content)
    # dst acks back to src
    src.on_ack(dst.recv_next, dst_win(dst))
    return out


def dst_win(s):
    return max(1, it.WINDOW - len(s.recv_buf))


def test_in_order_transfer():
    a, b = it.Stream(), it.Stream()
    for i in range(10):
        a.queue(f"m{i}".encode())
    got = []
    for _ in range(30):
        got += _deliver(a, b)
        if not a.unacked:
            break
    assert b"".join(got) == b"".join(f"m{i}".encode() for i in range(10))
    assert not a.unacked


def test_loss_and_reorder_recovers():
    rng = random.Random(42)
    a, b = it.Stream(), it.Stream()
    payload = [os.urandom(rng.randint(1, 300)) for _ in range(40)]
    for p in payload:
        a.queue(p)
    got, now = [], 0.0
    for _ in range(4000):
        now += it.RTO                       # advance past RTO so retransmits fire
        got += _deliver(a, b, drop=0.3, dup=0.1, reorder=True, rng=rng, now=now)
        if not a.unacked:
            break
    assert not a.unacked, "sender still has unacked segments"
    assert b"".join(got) == b"".join(payload)


def test_duplicates_are_not_redelivered():
    a, b = it.Stream(), it.Stream()
    a.queue(b"only-once")
    seq = next(iter(a.unacked))
    first = b.accept(seq, b"only-once")
    second = b.accept(seq, b"only-once")   # duplicate
    assert first == [b"only-once"] and second == []


def test_fin_is_ordered_after_data():
    a, b = it.Stream(), it.Stream()
    a.queue(b"data")
    a.queue_fin()
    assert a.sent_fin
    got = []
    for _ in range(10):
        got += _deliver(a, b)
        if not a.unacked:
            break
    assert got[0] == b"data" and got[-1] is it._FIN
    assert not a.unacked


def test_window_limits_inflight():
    a = it.Stream()
    a.peer_win = it.WINDOW
    for _ in range(it.WINDOW + 50):
        if a.can_send():
            a.queue(b"x")
    assert len(a.unacked) <= it.WINDOW
    assert not a.can_send()
