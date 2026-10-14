"""Applies the WireGuard configuration pushed by the panel and reports per-peer
traffic and handshakes.

Unlike Xray, bringing wg0 up/down and reading its live state both need root or
CAP_NET_ADMIN, which this agent deliberately does not have. Two privileged helpers
installed by deploy/install-wireguard.sh do that instead: ipf3-wireguard-reload
.service (triggered via ipf3-wireguard-config.path when this module writes a new
config) actually runs wg-quick, and ipf3-wireguard-stats.timer periodically dumps
`wg show wg0 dump` to a world-readable file this module reads. This module itself
never needs a privileged syscall — checking whether wg0 exists and is up is a plain
read (`ip link show`), same as everything else the agent does."""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("IPF3_WG_CONFIG", "/etc/ipf3/wireguard/wg0.conf"))
HASH_PATH = CONFIG_PATH.with_name("config.hash")
STATS_PATH = Path(os.environ.get("IPF3_WG_STATS", "/run/ipf3-wg/stats.dump"))
IFACE = "wg0"


def installed() -> bool:
    if not (shutil.which("wg") and shutil.which("wg-quick") and CONFIG_PATH.parent.is_dir()):
        return False
    # wg-quick itself falls back to a userspace implementation (wireguard-go) when
    # the kernel module isn't loaded; either counts as "installed".
    return os.path.exists("/sys/module/wireguard") or shutil.which("wireguard-go") is not None


async def _run(*args: str, timeout: float = 10) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "timeout"
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def is_running() -> bool:
    """True when wg0 exists and is administratively up. A plain netlink read, no
    privilege needed — unlike reading peer state, which `wg show` requires root for."""
    code, out = await _run("ip", "-o", "link", "show", IFACE, timeout=5)
    if code != 0 or "<" not in out or ">" not in out:
        return False
    flags = out.split("<", 1)[1].split(">", 1)[0].split(",")
    return "UP" in flags


def current_hash() -> str | None:
    try:
        return HASH_PATH.read_text().strip() or None
    except OSError:
        return None


def _sanity_check(text: str) -> str | None:
    """A cheap structural check only — catches a truncated/corrupted transfer.
    `wg-quick strip` cannot be used for this: it accepts almost any text (no
    section headers, missing keys, garbage lines) without complaint, since it's a
    reformatter, not a validator. Real validation already happened on the panel,
    which generated this text from its own trusted model."""
    if "[Interface]" not in text or "PrivateKey" not in text:
        return "missing [Interface]/PrivateKey — config looks truncated or corrupted"
    return None


async def apply(text: str, config_hash: str) -> str | None:
    """Write a new wg0.conf atomically. Applying it (wg-quick up/syncconf) happens
    in the privileged reload service once this file changes — this process has no
    privilege to do that itself, nor to meaningfully validate it beforehand."""
    if (err := _sanity_check(text)) is not None:
        return err
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_PATH.parent, prefix=".wg0.", suffix=".conf")
    try:
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, CONFIG_PATH)  # triggers ipf3-wireguard-config.path -> reload
        HASH_PATH.write_text(config_hash)
        return None
    finally:
        Path(tmp).unlink(missing_ok=True)


def parse_dump(lines: list[str]) -> dict[str, dict[str, int]]:
    """pubkey(b64) -> {"handshake": unix ts, "rx": cumulative bytes, "tx": cumulative
    bytes} from `wg show <iface> dump` output. The first line (the interface's own
    keys/port/fwmark) has 4 fields and is skipped; peer lines have 8."""
    peers: dict[str, dict[str, int]] = {}
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 8:
            continue
        pubkey, _psk, _endpoint, _allowed, handshake, rx, tx, _keepalive = fields
        try:
            peers[pubkey] = {"handshake": int(handshake), "rx": int(rx), "tx": int(tx)}
        except ValueError:
            continue
    return peers


def read_dump() -> dict[str, dict[str, int]]:
    try:
        lines = STATS_PATH.read_text().splitlines()
    except OSError:
        return {}
    return parse_dump(lines)


@dataclass
class TrafficCounter:
    """wg's rx/tx counters only ever grow (or reset to 0 if the interface restarts).
    This keeps the last cumulative reading per peer and turns new dumps into deltas,
    buffered until the panel acknowledges them — the same shape as Xray's own
    TrafficCounter, so a network failure never loses traffic.

    From the server's side of the tunnel: rx = bytes received from the peer (the
    user's upload), tx = bytes sent to the peer (the user's download) — matching
    Xray's uplink/downlink convention."""

    _last: dict[str, tuple[int, int]] = field(default_factory=dict)
    pending: dict[str, dict[str, int]] = field(default_factory=dict)

    def update(self, peers: dict[str, dict[str, int]]) -> None:
        for pubkey, p in peers.items():
            rx, tx = p["rx"], p["tx"]
            prev = self._last.get(pubkey)
            self._last[pubkey] = (rx, tx)
            if prev is None:
                continue  # first sighting: nothing to diff against yet
            prx, ptx = prev
            d_up = rx - prx if rx >= prx else 0
            d_down = tx - ptx if tx >= ptx else 0
            if d_up or d_down:
                u = self.pending.setdefault(pubkey, {"up": 0, "down": 0})
                u["up"] += d_up
                u["down"] += d_down

    def take(self) -> dict[str, dict[str, int]]:
        p, self.pending = self.pending, {}
        return p

    def restore(self, p: dict[str, dict[str, int]]) -> None:
        for k, t in p.items():
            u = self.pending.setdefault(k, {"up": 0, "down": 0})
            u["up"] += t["up"]
            u["down"] += t["down"]
