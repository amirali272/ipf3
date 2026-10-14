"""WireGuard: server/peer config text, keys, and IP allocation.

Unlike Xray, WireGuard is a real network interface (`wg0`), not a process the agent
starts directly — a separate, narrowly-privileged systemd unit on the node brings it
up with `wg-quick` / `wg syncconf` when the agent writes a new desired config (see
docs/VPN.md). This module only builds that config text and the per-user client
config; it has no I/O of its own.
"""

from __future__ import annotations

import hashlib
import ipaddress
from typing import Any

import base64

from .x25519 import raw_private, raw_public
from ..models import WgInbound, WgPeer


def generate_keypair() -> tuple[str, str]:
    """WireGuard keys are Curve25519 like REALITY's, just base64-with-padding encoded."""
    priv = raw_private()
    pub = raw_public(priv)
    return base64.b64encode(priv).decode(), base64.b64encode(pub).decode()


def detect_egress_iface(routes: list[dict[str, Any]]) -> str | None:
    """The device of the node's IPv4 default route, from its latest inventory."""
    for r in routes or []:
        if r.get("dst") in (None, "default") and r.get("table", "main") == "main" and r.get("dev"):
            return str(r["dev"])[:32]
    return None


def next_free_address(network: str, taken: set[str]) -> str:
    """First host address in `network` (skipping .0/network, .1/server, broadcast)
    that isn't in `taken`. Raises if the pool is exhausted."""
    net = ipaddress.ip_network(network, strict=False)
    server_ip = next(net.hosts())
    for host in net.hosts():
        if host == server_ip:
            continue
        s = str(host)
        if s not in taken:
            return s
    raise ValueError("no free addresses left in this WireGuard network")


def _nat_rules(inbound: WgInbound) -> tuple[str, str]:
    if not inbound.egress_iface:
        return "", ""
    net = inbound.network
    iface, out = inbound.egress_iface, inbound.interface
    up = f"iptables -t nat -A POSTROUTING -s {net} -o {iface} -j MASQUERADE; iptables -A FORWARD -i {out} -j ACCEPT; iptables -A FORWARD -o {out} -j ACCEPT"
    down = f"iptables -t nat -D POSTROUTING -s {net} -o {iface} -j MASQUERADE; iptables -D FORWARD -i {out} -j ACCEPT; iptables -D FORWARD -o {out} -j ACCEPT"
    return up, down


def build_server_config(inbound: WgInbound, peers: list[WgPeer]) -> str:
    """The node's desired `wg0.conf` (wg-quick format). Disabled peers and the
    inbound's own disabled state are left out, so toggling enforces immediately."""
    lines = [
        "[Interface]",
        f"PrivateKey = {inbound.private_key}",
        f"Address = {next(ipaddress.ip_network(inbound.network, strict=False).hosts())}/{ipaddress.ip_network(inbound.network, strict=False).prefixlen}",
        f"ListenPort = {inbound.listen_port}",
        f"MTU = {inbound.mtu}",
    ]
    up, down = _nat_rules(inbound)
    if up:
        lines += [f"PostUp = {up}", f"PostDown = {down}"]
    if inbound.enabled:
        for p in sorted(peers, key=lambda p: p.id):
            if not p.enabled:
                continue
            lines += ["", "[Peer]", f"PublicKey = {p.public_key}"]
            if p.preshared_key:
                lines.append(f"PresharedKey = {p.preshared_key}")
            lines.append(f"AllowedIPs = {p.address}/32")
    return "\n".join(lines) + "\n"


def config_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def peer_config(inbound: WgInbound, peer: WgPeer) -> str:
    """The client's own wg-quick config — what the user imports or scans as a QR."""
    prefix = ipaddress.ip_network(inbound.network, strict=False).prefixlen
    lines = [
        "[Interface]",
        f"PrivateKey = {peer.private_key}",
        f"Address = {peer.address}/{prefix}",
    ]
    if inbound.dns:
        lines.append(f"DNS = {inbound.dns}")
    lines += [
        "",
        "[Peer]",
        f"PublicKey = {inbound.public_key}",
    ]
    if peer.preshared_key:
        lines.append(f"PresharedKey = {peer.preshared_key}")
    lines += [
        "AllowedIPs = 0.0.0.0/0, ::/0",
        f"Endpoint = {inbound.address}:{inbound.listen_port}",
    ]
    if inbound.persistent_keepalive:
        lines.append(f"PersistentKeepalive = {inbound.persistent_keepalive}")
    return "\n".join(lines) + "\n"
