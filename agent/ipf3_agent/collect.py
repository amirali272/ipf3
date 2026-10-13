"""Collection of real host telemetry from /proc, psutil and iproute2.

Everything here runs unprivileged: /proc/net/* and `ip -j` are world readable,
and `ss` without -p does not need root."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from . import __version__

TCP_STATES = {
    "01": "established",
    "02": "syn_sent",
    "03": "syn_recv",
    "04": "fin_wait1",
    "05": "fin_wait2",
    "06": "time_wait",
    "07": "close",
    "08": "close_wait",
    "09": "last_ack",
    "0A": "listen",
    "0B": "closing",
}


def _read(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError:
        return ""


def tcp_state_counts(proc_root: str = "/proc") -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in ("net/tcp", "net/tcp6"):
        for line in _read(f"{proc_root}/{f}").splitlines()[1:]:
            parts = line.split()
            if len(parts) > 3:
                state = TCP_STATES.get(parts[3].upper(), "other")
                counts[state] = counts.get(state, 0) + 1
    return counts


def udp_socket_count(proc_root: str = "/proc") -> int:
    return sum(
        max(0, len(_read(f"{proc_root}/{f}").splitlines()) - 1) for f in ("net/udp", "net/udp6")
    )


def tcp_retrans_segs(proc_root: str = "/proc") -> int | None:
    lines = [l.split() for l in _read(f"{proc_root}/net/snmp").splitlines() if l.startswith("Tcp:")]
    if len(lines) >= 2:
        header, values = lines[0], lines[1]
        if "RetransSegs" in header:
            try:
                return int(values[header.index("RetransSegs")])
            except (ValueError, IndexError):
                return None
    return None


def os_release() -> str:
    data = _read("/etc/os-release")
    for line in data.splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.platform()


def detect_tools() -> dict[str, bool]:
    return {
        "iperf3": shutil.which("iperf3") is not None,
        "ping": shutil.which("ping") is not None,
        "traceroute": shutil.which("traceroute") is not None,
        "mtr": shutil.which("mtr") is not None,
        "dns": True,  # dnspython
        "ip": shutil.which("ip") is not None,
        "ss": shutil.which("ss") is not None,
    }


def system_info(name: str = "") -> dict:
    return {
        "hostname": socket.getfqdn() or socket.gethostname(),
        "os_name": os_release(),
        "kernel": platform.release(),
        "agent_version": __version__,
        "cpu_count": psutil.cpu_count(logical=True),
        "capabilities": {"tools": detect_tools(), "arch": platform.machine()},
    }


@dataclass
class _Counters:
    t: float
    nics: dict


def is_physical(iface: str, sys_root: str = "/sys/class/net") -> bool:
    """True for NICs backed by a device (incl. virtio on VPSes). Bridges, veth,
    tun/wg, ifb and docker interfaces are virtual and would double count traffic."""
    return os.path.exists(f"{sys_root}/{iface}/device")


def primary_interfaces(names: list[str], sys_root: str = "/sys/class/net") -> set[str]:
    """Interfaces whose traffic makes up the host total. Falls back to every
    non-loopback interface on hosts without device-backed NICs (e.g. OpenVZ venet0)."""
    phys = {n for n in names if n != "lo" and is_physical(n, sys_root)}
    return phys or {n for n in names if n != "lo"}


class NetRateMeter:
    """Lightweight per-interface bit-rate meter for the live view (no CPU/memory
    work, so it can run every couple of seconds)."""

    def __init__(self, exclude_interfaces: list[str] | None = None):
        self.exclude = set(exclude_interfaces or [])
        self._prev: _Counters | None = None

    def sample(self) -> list[dict] | None:
        now = time.monotonic()
        nics = {k: v for k, v in psutil.net_io_counters(pernic=True).items() if k not in self.exclude}
        prev, self._prev = self._prev, _Counters(now, nics)
        if prev is None or now <= prev.t:
            return None
        dt = now - prev.t
        primary = primary_interfaces(list(nics))
        out = []
        for name, c in nics.items():
            p = prev.nics.get(name)
            if p is None:
                continue
            rx = c.bytes_recv - p.bytes_recv if c.bytes_recv >= p.bytes_recv else 0
            tx = c.bytes_sent - p.bytes_sent if c.bytes_sent >= p.bytes_sent else 0
            out.append({"iface": name[:64], "rx_bps": rx * 8 / dt, "tx_bps": tx * 8 / dt, "primary": name in primary})
        return out


class MetricsCollector:
    """Computes per-interval rates from monotonically increasing kernel counters."""

    def __init__(self, exclude_interfaces: list[str] | None = None):
        self.exclude = set(exclude_interfaces or [])
        self._prev: _Counters | None = None
        psutil.cpu_percent(interval=None)  # prime the CPU counter

    def _nics(self) -> dict:
        return {k: v for k, v in psutil.net_io_counters(pernic=True).items() if k not in self.exclude}

    def sample(self) -> dict | None:
        now = time.monotonic()
        nics = self._nics()
        prev, self._prev = self._prev, _Counters(now, nics)
        if prev is None:
            return None
        dt = now - prev.t
        if dt <= 0:
            return None
        interfaces = []
        primary = primary_interfaces(list(nics))
        for name, c in nics.items():
            p = prev.nics.get(name)
            if p is None:
                continue

            def d(a: int, b: int) -> int:
                # Counter reset (interface re-created / 32-bit wrap): skip delta.
                return a - b if a >= b else 0

            interfaces.append(
                {
                    "iface": name[:64],
                    "rx_bps": d(c.bytes_recv, p.bytes_recv) * 8 / dt,
                    "tx_bps": d(c.bytes_sent, p.bytes_sent) * 8 / dt,
                    "rx_pps": d(c.packets_recv, p.packets_recv) / dt,
                    "tx_pps": d(c.packets_sent, p.packets_sent) / dt,
                    "rx_errs": d(c.errin, p.errin),
                    "tx_errs": d(c.errout, p.errout),
                    "rx_drops": d(c.dropin, p.dropin),
                    "tx_drops": d(c.dropout, p.dropout),
                    "rx_bytes": d(c.bytes_recv, p.bytes_recv),
                    "tx_bytes": d(c.bytes_sent, p.bytes_sent),
                    "primary": name in primary,
                }
            )
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        try:
            disk = psutil.disk_usage("/").percent
        except OSError:
            disk = None
        load = os.getloadavg()
        tcp = tcp_state_counts()
        return {
            "system": {
                "cpu_percent": psutil.cpu_percent(interval=None),
                "load1": load[0],
                "load5": load[1],
                "load15": load[2],
                "mem_total": vm.total,
                "mem_used": vm.total - vm.available,
                "mem_percent": vm.percent,
                "swap_percent": sw.percent,
                "disk_percent": disk,
                "uptime_seconds": int(time.time() - psutil.boot_time()),
                "tcp_established": tcp.get("established", 0),
                "tcp_listen": tcp.get("listen", 0),
                "tcp_time_wait": tcp.get("time_wait", 0),
                "udp_sockets": udp_socket_count(),
                "tcp_retrans_segs": tcp_retrans_segs(),
            },
            "interfaces": interfaces,
        }


# --------------------------------------------------------------------------- inventory
def _run_json(args: list[str]) -> list:
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
        return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return []


def interfaces_inventory() -> list[dict]:
    stats = psutil.net_if_stats()
    out = []
    for link in _run_json(["ip", "-j", "addr", "show"]):
        name = link.get("ifname")
        st = stats.get(name)
        out.append(
            {
                "name": name,
                "state": link.get("operstate"),
                "mtu": link.get("mtu"),
                "mac": link.get("address"),
                "link_type": link.get("link_type"),
                "flags": link.get("flags", []),
                "speed_mbps": st.speed if st and st.speed else None,
                "duplex": str(st.duplex).rsplit(".", 1)[-1].lower() if st else None,
                "addresses": [
                    f"{a.get('local')}/{a.get('prefixlen')}"
                    for a in link.get("addr_info", [])
                    if a.get("local")
                ],
            }
        )
    if not out:  # iproute2 missing: fall back to psutil
        for name, addrs in psutil.net_if_addrs().items():
            st = stats.get(name)
            out.append(
                {
                    "name": name,
                    "state": "up" if st and st.isup else "down",
                    "mtu": st.mtu if st else None,
                    "speed_mbps": st.speed if st and st.speed else None,
                    "addresses": [a.address for a in addrs if a.family in (socket.AF_INET, socket.AF_INET6)],
                }
            )
    return out


def routes_inventory(ipv6: bool = False) -> list[dict]:
    args = ["ip", "-6", "-j", "route", "show", "table", "all"] if ipv6 else ["ip", "-j", "route", "show", "table", "all"]
    routes = []
    for r in _run_json(args)[:5000]:
        if r.get("type") in ("local", "broadcast", "multicast", "anycast") and r.get("table") == "local":
            continue
        routes.append(
            {
                "dst": r.get("dst"),
                "gateway": r.get("gateway"),
                "dev": r.get("dev"),
                "protocol": r.get("protocol"),
                "scope": r.get("scope"),
                "metric": r.get("metric"),
                "prefsrc": r.get("prefsrc"),
                "table": r.get("table", "main"),
                "type": r.get("type", "unicast"),
            }
        )
    return routes


def parse_ss(output: str, limit: int) -> list[dict]:
    """Parse `ss -H -tuna` output (no process info => no privileges needed)."""
    conns = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        netid, state, recvq, sendq, local, peer = parts[:6]
        conns.append(
            {
                "proto": netid,
                "state": state,
                "recv_q": int(recvq) if recvq.isdigit() else None,
                "send_q": int(sendq) if sendq.isdigit() else None,
                "local": local,
                "peer": peer,
            }
        )
        if len(conns) >= limit:
            break
    return conns


def connections_inventory(limit: int = 2000) -> list[dict]:
    try:
        out = subprocess.run(["ss", "-H", "-tuna"], capture_output=True, text=True, timeout=10, check=False)
        return parse_ss(out.stdout, limit) if out.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        return []


def parse_resolv_conf(text: str) -> dict:
    ns, search, options = [], [], []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, rest = line.partition(" ")
        if key == "nameserver":
            ns.append(rest.strip())
        elif key in ("search", "domain"):
            search.extend(rest.split())
        elif key == "options":
            options.extend(rest.split())
    return {"nameservers": ns, "search": search, "options": options}


def dns_inventory() -> dict:
    info = parse_resolv_conf(_read("/etc/resolv.conf"))
    upstream = _read("/run/systemd/resolve/resolv.conf")
    if upstream:
        info["upstream_nameservers"] = parse_resolv_conf(upstream)["nameservers"]
        info["resolver"] = "systemd-resolved"
    return info


def host_inventory(max_connections: int) -> dict:
    cpu_model = ""
    for line in _read("/proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            cpu_model = line.split(":", 1)[1].strip()
            break
    return {
        "interfaces": interfaces_inventory(),
        "routes": routes_inventory(False),
        "routes6": routes_inventory(True),
        "connections": connections_inventory(max_connections),
        "dns": dns_inventory(),
        "system": {
            "os": os_release(),
            "kernel": platform.release(),
            "cpu_model": cpu_model,
            "cpu_count": psutil.cpu_count(logical=True),
            "mem_total": psutil.virtual_memory().total,
            "boot_time": psutil.boot_time(),
            "python": platform.python_version(),
            "tools": detect_tools(),
        },
    }
