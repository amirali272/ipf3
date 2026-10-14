# VPN (Xray-core)

Unknown Monitor manages Xray-core on your servers. The panel holds users and inbounds.
Each server running the agent with Xray enabled is a **node**. The agent pulls its
node's config from the panel, validates it with `xray run -test`, and installs it. It
reports per-user traffic every 10 seconds.

```
 Panel (users, inbounds, limits) ──HTTPS──► agent on node ──► /etc/ipf3/xray/config.json
                                  ◄──────── per-user traffic, online users, Xray status
                                                    │  (systemd path unit restarts ipf3-xray)
 VPN clients ──────── VLESS / VMess / Trojan / Shadowsocks ───────► Xray-core on the node
```

## Enabling a node

### Adding a node on another server

Inbounds can be served from any number of servers. The panel stays where it is, and
clients connect directly to the node.

1. In the panel, go to **VPN → Inbounds & nodes → Add node**, enter a name, then
   click **Generate command**.
2. Run the command it shows, as root, on the new Ubuntu 22.04/24.04 server:

   ```bash
   bash <(curl -fsSL "https://raw.githubusercontent.com/amirali272/ipf3/claude/gracious-ramanujan-enb5r9/install.sh?$(date +%s)") \
     --node --panel https://panel.example.com --token ipf3e_… --name de-1
   ```

   It installs the agent and Xray, enrolls with the single-use token (valid 24 h) and
   starts reporting. A self-signed panel certificate is trusted automatically in this
   mode. Add `--iperf3` to also run an iperf3 endpoint there.
3. The dialog shows **Connected** once the node reports in. When you create an
   inbound, pick the node as its server. Port 443 is free on a node, so you can use it
   there (`ufw allow 443` if the firewall is enabled). Share links use the node's
   address unless you set a different one on the inbound.

### Other ways to enable a node

- **New server:** run `sudo ./install.sh`, choose *Install panel + agent* or *Add this
  server to an existing panel*, and answer **yes** to "Use this server as a VPN node".
- **Existing agent:** run `sudo ./install.sh`, choose *Upgrade*, and answer **yes**. Or
  run `sudo ./deploy/install-xray.sh` and then `sudo systemctl restart ipf3-agent`.

`deploy/install-xray.sh` downloads the latest Xray-core release, or `XRAY_VERSION=v…`,
from GitHub. It checks the zip against the published SHA-256. It then installs the
binary and the geo files, and creates three units:

| Unit | Role |
|---|---|
| `ipf3-xray.service` | Runs Xray as the unprivileged `ipf3-xray` user. Its only capability is `CAP_NET_BIND_SERVICE` (ports < 1024). |
| `ipf3-xray-config.path` | Watches `/etc/ipf3/xray/config.json`. |
| `ipf3-xray-reload.service` | Restarts Xray when the config changes. The agent itself has no privileges. |

## Inbounds

In the panel, open **VPN → Inbounds & nodes → New inbound**. Pick a preset or build
your own:

| Protocol | Transports | Security |
|---|---|---|
| VLESS | TCP, XHTTP, WebSocket, gRPC, HTTPUpgrade | none, TLS, REALITY (TCP/XHTTP/gRPC), XTLS Vision flow (TCP + TLS/REALITY) |
| VMess | TCP, XHTTP, WebSocket, gRPC, HTTPUpgrade | none, TLS |
| Trojan | TCP, XHTTP, WebSocket, gRPC, HTTPUpgrade | none, TLS, REALITY |
| Shadowsocks | TCP + UDP | AEAD (aes-128/256-gcm, (x)chacha20-poly1305) and 2022 (blake3-aes-128/256-gcm, chacha20-poly1305) |

**Recommended: VLESS + REALITY** (TCP with Vision, or XHTTP). It needs no domain or
certificate. *Generate* creates the X25519 key pair and a short ID. Choose a target
site that supports TLS 1.3, with server names that are valid for it.

Xray 26 marks VMess, Trojan, Shadowsocks, WebSocket, gRPC and HTTPUpgrade as
**deprecated**. They still work, and the panel shows a warning when you pick them.

TLS inbounds need a certificate that clients can verify (Xray 26 removed
`allowInsecure`). Paste the PEM certificate and key, or give file paths on the node
that the `ipf3-xray` user can read.

**On the panel server itself, port 443 is taken by the panel.** Use another port
there, for example 8443 or 2053, or put the VPN on a separate server. If the node runs
a firewall, open the inbound port, for example `ufw allow 8443`.

Configs block access to private networks (`geoip:private`, which includes the node's
localhost services) and BitTorrent.

## WireGuard

**VPN → WireGuard** manages native WireGuard peers alongside Xray, using the OS's own
`wg`/`wg-quick` — not an Xray inbound (Xray-core has no WireGuard inbound). One wg0
interface per node:

1. **Add WireGuard inbound**: node, UDP listen port, a private peer network (e.g.
   `10.70.0.0/24`), the public address clients connect to, and the DNS pushed to
   clients. The egress interface for NAT is auto-detected from the node's routes, or
   set it explicitly if a node has multiple NICs.
2. **Add peer**, per user. The panel generates both the server's and the peer's
   Curve25519 keypair plus a pre-shared key and allocates the next free address in the
   network — WireGuard needs the client's private key, unlike Xray, so there's no
   "subscription link" here, just a config to copy, download or scan as a QR in the
   official WireGuard app.

Traffic and online status come from `wg show`, which needs root — a privileged helper
installed by `install-wireguard.sh` dumps it to a file the agent reads, the same
two-stage privilege split as the Xray config reload path. Peer traffic counts toward
the same per-user usage, limits and expiry as Xray.

**Prefer WireGuard when you need near-line-rate speed, a router/whole-device tunnel,
or the native OS client — not for deep-packet-inspection-censored networks.** Its
packet format is far easier to fingerprint than VLESS + REALITY/XHTTP, which is what
survives there.

## Who is connected

**Connected IPs.** Every ~10 s, each node reads Xray's per-user online IP list
(`statsonlineiplist`) and reports it to the panel. On the Users page, each user with
active connections gets an `N IP` badge. *Activity* lists every connected IP with its
node and last activity. Xray does not track clients connecting from loopback
addresses.

**Apps.** Each subscription update is recorded. The record holds the app's User-Agent
(v2rayNG, Hiddify, Streisand, Happ, Clash Meta, sing-box, …), its version, the IP it
came from and an update count. The panel keeps the 20 most recent apps per user.

**Subscription page.** This is the page users see when they open their link in a
browser. It shows usage, expiry, connected IPs and apps, one-tap import buttons and QR
codes, in Persian or English.

Connected IPs need agents upgraded to this version.

## Outbounds & routing

**VPN → Outbounds & routing** lets a node send user traffic on to another server
instead of straight out to the internet. For example, users connect to a node in
Iran, and their traffic leaves from a server in Germany or through WARP.

**Outbounds.** Paste a config link: `vless://`, `vmess://`, `trojan://`, `ss://`,
`socks://`, `http(s)://` or `wireguard://`. You can also paste an Xray outbound or a
full client config as JSON. The panel converts the link into an Xray outbound,
previews it, and lets you limit it to selected nodes. When Xray is installed on the
panel host, the panel checks every outbound with `xray run -test` before saving it,
and each node checks its full config again before applying it. Traffic is counted
per outbound.

**Routing rules.** Rules are checked from top to bottom, and the first match decides
where the traffic goes: **Direct**, **Block** or an outbound. All conditions you fill
in must match. The conditions are:

- domains: `geosite:…`, `domain:`, `full:`, `keyword:`, `regexp:`
- IPs: `geoip:…` or a CIDR
- users
- inbounds
- destination ports
- TCP/UDP
- sniffed protocol

A rule with no conditions matches all traffic. Templates cover the common cases:
Iranian sites direct, block ads, everything through an outbound, some sites through an
outbound, some users through an outbound. Two built-in rules always come first:
private networks are blocked, and BitTorrent is blocked. Traffic that no rule matches
goes out directly.

A rule that uses an outbound applies only on the nodes where that outbound is
available. Changes reach the nodes within about 10 seconds. Per-outbound traffic needs
agents upgraded to this version.

## Users

Each user has:

- A data limit in decimal GB, where 0 means unlimited.
- An expiry: never, in N days, or on a specific date.
- Access to either all inbounds (including ones added later) or a chosen subset.
- An optional note.

Status is computed as **active / expired / limited / disabled**. Only active users are
written into node configs, so limits and expiry take effect within about 10 seconds.
These actions are also available:

- **Reset traffic** sets the usage counters back to zero.
- **Revoke links** issues a new UUID, password and subscription token. Every old config
  stops working.

## Subscriptions

Every user has a link: `https://<panel>/sub/<token>`.

| Client | Response |
|---|---|
| v2rayNG, Hiddify, Streisand, V2Box, NekoBox, … | Base64 list of `vless://`, `vmess://`, `trojan://` and `ss://` links |
| Clash Meta / mihomo / Stash (detected by User-Agent, or `?format=clash`) | Clash Meta YAML |
| Browser | Redirects to `/s/<token>`, a status page with usage, expiry, QR codes and one-tap import buttons |
| `?format=links` | Plain links, one per line |

Responses include `subscription-userinfo` (upload, download, total and expire), which
clients use to show remaining traffic, plus `profile-update-interval: 12`.

## Roles

| Action | Role |
|---|---|
| View users, inbounds, nodes | viewer |
| Create, edit, reset or revoke users | operator |
| Manage inbounds and generate keys | admin |

## Verified behaviour

The test suite (`server/tests/test_vpn*.py`) runs a real Xray 26 server with the
generated config and real Xray clients built from the share links. It checks traffic
through VLESS REALITY (Vision, XHTTP, gRPC), VLESS WS + TLS, VMess HTTPUpgrade,
Trojan TLS, Shadowsocks AEAD and Shadowsocks 2022. It also checks that per-user
statistics are recorded.
