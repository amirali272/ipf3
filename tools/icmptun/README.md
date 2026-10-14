# icmptun — a tunnel over ICMP (ping)

A transport of last resort for networks that pass ICMP echo (ping) but block or
throttle normal TCP/UDP. It carries a TCP stream inside ICMP echo request/reply
packets, with its own reliability layer (sequence numbers, cumulative acks, timed
retransmission and reordering) because ICMP is lossy and unordered.

It is **not** an Xray transport — Xray-core has no ICMP transport. icmptun sits
**underneath** Xray: the client exposes a local TCP port and forwards it, over
ICMP, to a TCP target on the node (meant to be a local Xray inbound bound to
`127.0.0.1`). All authentication and encryption stay in Xray; icmptun only moves
bytes and adds a cheap keyed check to drop stray/spoofed packets.

```
  v2ray client ──TCP──► icmptun client ──ICMP echo──► icmptun server ──TCP──► Xray inbound (127.0.0.1)
```

## Read this before using it

ICMP tunnelling is slow and fragile by nature:

- **Phones can't use it.** No v2rayNG / Hiddify / Streisand / sing-box supports
  ICMP. It needs the custom client below, with root/raw sockets — practically
  Linux only. iOS forbids raw sockets outright.
- **Many networks drop it.** Mobile carriers and lots of home routers rate-limit
  or block ICMP to third-party hosts, so it often never reaches the node.
- **It's easy to detect and block.** A steady stream of large ping packets is an
  obvious pattern; censors block it quickly.
- **It's slow.** Expect well under a megabit and high latency.

For day-to-day use, VLESS + REALITY or XHTTP (already in the panel) are far more
reliable. Use icmptun only where literally nothing but ping gets out.

## Requirements

- Python 3.10+ (standard library only), Linux.
- Raw sockets on both ends: run as root, or grant the capability once:

  ```bash
  sudo setcap cap_net_raw+ep "$(command -v python3)"
  ```

## Run it

On the node (server), forward ICMP to a local Xray inbound listening on
`127.0.0.1:8443`:

```bash
sudo python3 icmptun.py --key "a-long-shared-secret" server --target 127.0.0.1:8443
```

On the user's Linux machine (client), expose a local port that tunnels to the
node:

```bash
sudo python3 icmptun.py --key "a-long-shared-secret" client --server <node-ip> --listen 127.0.0.1:8443
```

Now point your VPN client's config at `127.0.0.1:8443` instead of the node's real
address/port. The inbound's address in the share link should be set to
`127.0.0.1` (or edit the config locally), since the client reaches it through the
tunnel.

`--key` (or the `ICMPTUN_KEY` environment variable) must match on both ends. The
key is not a substitute for Xray's own TLS/REALITY — keep using an encrypted
inbound as the target.

Also allow ICMP echo through any firewall on the node (e.g. `ufw allow in proto
icmp` / an iptables accept for `icmp echo-request`). Leaving the kernel's own ping
responder enabled is fine; the client ignores kernel replies.

## How the wire format works

Each ICMP echo payload is:

```
MAGIC(4) ver(1) flags(1) session(2) seq(4) ack(4) win(2) dlen(2) data(dlen) tag(8)
```

- `flags` bit0 = direction (0 = client→server, 1 = server→client), bit1 = FIN.
- The client sends echo **requests** (type 8); the server sends echo **replies**
  (type 0). Each side ignores packets carrying its own direction bit, so the
  kernel's automatic echo reply (which reflects the client's payload verbatim) is
  dropped.
- `session` (also the ICMP identifier) multiplexes many TCP connections over one
  raw socket; each local connection is a session with its own reliable stream.
- `tag` is `HMAC-SHA256(key, header+data)[:8]`.
- The client keeps sending (polling) while idle so the server's replies can
  traverse NAT.

## Tests

`test_icmptun.py` covers framing and the reliability engine (loss, reordering,
retransmission, FIN) and needs no root:

```bash
python3 -m pytest tools/icmptun/test_icmptun.py -q
```
