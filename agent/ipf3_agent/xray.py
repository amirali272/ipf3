"""Applies the Xray configuration pushed by the panel and reports per-user traffic.

The agent never restarts Xray itself (it has no privileges for that): it writes a
validated config atomically to CONFIG_PATH, and the ipf3-xray-config.path systemd
unit restarts ipf3-xray.service whenever that file changes."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

XRAY_BIN = os.environ.get("IPF3_XRAY_BIN", "/usr/local/bin/xray")
ASSET_DIR = os.environ.get("IPF3_XRAY_ASSETS", "/usr/local/share/xray")
CONFIG_PATH = Path(os.environ.get("IPF3_XRAY_CONFIG", "/etc/ipf3/xray/config.json"))
HASH_PATH = CONFIG_PATH.with_name("config.hash")


def installed() -> bool:
    return os.path.isfile(XRAY_BIN) and os.access(XRAY_BIN, os.X_OK) and CONFIG_PATH.parent.is_dir()


async def _run(*args: str, timeout: float = 20) -> tuple[int, str]:
    env = {**os.environ, "XRAY_LOCATION_ASSET": ASSET_DIR}
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL, env=env
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "timeout"
    return proc.returncode or 0, out.decode("utf-8", "replace")


async def version() -> str | None:
    code, out = await _run(XRAY_BIN, "version", timeout=10)
    if code != 0 or not out:
        return None
    parts = out.split()
    return parts[1] if len(parts) > 1 else None


async def is_running() -> bool:
    if shutil.which("systemctl"):
        code, _ = await _run("systemctl", "is-active", "--quiet", "ipf3-xray.service", timeout=10)
        if code in (0, 3, 4):  # 3/4: inactive / unknown unit
            return code == 0
    # No usable systemd: look for an xray process running our config.
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if cmd and cmd[0].endswith(b"xray") and str(CONFIG_PATH).encode() in cmd:
            return True
    return False


def current_hash() -> str | None:
    try:
        return HASH_PATH.read_text().strip() or None
    except OSError:
        return None


async def apply(config: dict, config_hash: str) -> str | None:
    """Validate and atomically install a config. Returns an error message or None."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_PATH.parent, prefix=".config.", suffix=".json")
    try:
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=1)
        code, out = await _run(XRAY_BIN, "run", "-test", "-c", tmp)
        if code != 0:
            lines = [ln for ln in out.splitlines() if ln.strip() and "Warning" not in ln]
            return "\n".join(lines[-15:]) or f"xray -test exited with {code}"
        os.replace(tmp, CONFIG_PATH)  # triggers ipf3-xray-config.path -> restart
        HASH_PATH.write_text(config_hash)
        return None
    finally:
        Path(tmp).unlink(missing_ok=True)


@dataclass
class TrafficCounter:
    """Deltas read with -reset are kept until the panel acknowledges them, so a
    network failure never loses traffic."""

    pending: dict[str, dict[str, int]] = field(default_factory=dict)
    inbounds: dict[str, dict[str, int]] = field(default_factory=dict)
    outbounds: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(self, stats: list[dict]) -> None:
        for s in stats:
            parts = s.get("name", "").split(">>>")
            if len(parts) != 4 or parts[0] not in ("user", "inbound", "outbound") or parts[2] != "traffic":
                continue
            if parts[0] == "inbound" and parts[1] == "api":
                continue
            if parts[0] == "outbound" and not parts[1].startswith("out-"):
                continue
            try:
                value = int(s.get("value", 0))
            except (TypeError, ValueError):
                continue
            if value <= 0:
                continue
            key = "up" if parts[3] == "uplink" else "down"
            target = {"user": self.pending, "inbound": self.inbounds, "outbound": self.outbounds}[parts[0]]
            u = target.setdefault(parts[1], {"up": 0, "down": 0})
            u[key] += value

    def take(self) -> dict[str, dict[str, int]]:
        p, self.pending = self.pending, {}
        return p

    def take_inbounds(self) -> dict[str, dict[str, int]]:
        p, self.inbounds = self.inbounds, {}
        return p

    def take_outbounds(self) -> dict[str, dict[str, int]]:
        p, self.outbounds = self.outbounds, {}
        return p

    @staticmethod
    def _merge(into: dict[str, dict[str, int]], p: dict[str, dict[str, int]]) -> None:
        for k, t in p.items():
            u = into.setdefault(k, {"up": 0, "down": 0})
            u["up"] += t["up"]
            u["down"] += t["down"]

    def restore(
        self,
        p: dict[str, dict[str, int]],
        inbounds: dict[str, dict[str, int]] | None = None,
        outbounds: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self._merge(self.pending, p)
        if inbounds:
            self._merge(self.inbounds, inbounds)
        if outbounds:
            self._merge(self.outbounds, outbounds)


async def query_stats(api_port: int) -> list[dict]:
    code, out = await _run(XRAY_BIN, "api", "statsquery", "-s", f"127.0.0.1:{api_port}", "-pattern", ">>>traffic>>>", "-reset", timeout=10)
    if code != 0:
        return []
    try:
        return json.loads(out).get("stat", []) or []
    except json.JSONDecodeError:
        return []


async def online_users(api_port: int) -> list[str]:
    code, out = await _run(XRAY_BIN, "api", "statsgetallonlineusers", "-s", f"127.0.0.1:{api_port}", timeout=10)
    if code != 0:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    users = data.get("users") or data.get("onlineUsers") or []
    # entries look like "user>>>u12>>>online"
    out_users = []
    for u in users:
        name = u if isinstance(u, str) else str(u)
        parts = name.split(">>>")
        out_users.append(parts[1] if len(parts) >= 2 else name)
    return out_users
