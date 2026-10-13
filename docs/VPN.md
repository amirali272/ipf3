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
