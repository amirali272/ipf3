"""Execution of network tests. Commands are built as argv lists (never through a
shell) from parameters that are re-validated here as defence in depth, even
though the server validates them too."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import time
from dataclasses import dataclass
from typing import Any

import dns.exception
import dns.flags
import dns.message
import dns.name
import dns.query
import dns.rcode
import dns.rdatatype
import dns.resolver
import dns.reversename

MAX_OUTPUT = 2_000_000
_LABEL = re.compile(r"^(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")
_DNS_LABEL = re.compile(r"^(?!-)[A-Za-z0-9_-]{1,63}$")


class JobError(Exception):
    pass


def check_host(v: Any) -> str:
    if not isinstance(v, str) or not v or len(v) > 253 or v.startswith("-"):
        raise JobError("invalid target")
    try:
        return str(ipaddress.ip_address(v))
    except ValueError:
        pass
    name = v[:-1] if v.endswith(".") else v
    labels = name.split(".")
    if not all(_LABEL.match(l) for l in labels) or labels[-1].isdigit():
        raise JobError("invalid target")
    return v


def _int(params: dict, key: str, default: int, lo: int, hi: int) -> int:
    v = params.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise JobError(f"invalid {key}")
    return v


def _float(params: dict, key: str, default: float, lo: float, hi: float) -> float:
    v = params.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= float(v) <= hi:
        raise JobError(f"invalid {key}")
    return float(v)


def _choice(params: dict, key: str, default: str, choices: tuple[str, ...]) -> str:
    v = params.get(key, default)
    if v not in choices:
        raise JobError(f"invalid {key}")
    return v


@dataclass
class Command:
    argv: list[str]
    timeout: float
    ok_codes: tuple[int, ...] = (0,)


def build_iperf3(p: dict) -> Command:
    target = check_host(p.get("target"))
    duration = _int(p, "duration", 10, 1, 300)
    omit = _int(p, "omit", 0, 0, 10)
    argv = [
        "iperf3", "-c", target,
        "-p", str(_int(p, "port", 5201, 1, 65535)),
        "-t", str(duration),
        "-P", str(_int(p, "parallel", 1, 1, 32)),
        "-O", str(omit),
        "-J", "--connect-timeout", "5000",
    ]
    if _choice(p, "protocol", "tcp", ("tcp", "udp")) == "udp":
        argv.append("-u")
    if p.get("bitrate_bps") is not None:
        argv += ["-b", str(_int(p, "bitrate_bps", 0, 1000, 400_000_000_000))]
    if p.get("reverse") is True:
        argv.append("-R")
    if p.get("bidir") is True:
        argv.append("--bidir")
    if p.get("ipv6") is True:
        argv.append("-6")
    # iperf3 exits 1 on failure but still prints a JSON document with "error".
    return Command(argv, timeout=duration + omit + 30, ok_codes=(0, 1))


def build_ping(p: dict) -> Command:
    target = check_host(p.get("target"))
    count = _int(p, "count", 20, 1, 1000)
    interval = _float(p, "interval", 1.0, 0.2, 10.0)
    argv = ["ping", "-n", "-c", str(count), "-i", f"{interval:g}", "-s", str(_int(p, "packet_size", 56, 16, 65000)), "-W", "2"]
    if p.get("ipv6") is True:
        argv.append("-6")
    argv.append(target)
    # Exit 1 = some/all packets lost: still a valid measurement.
    return Command(argv, timeout=count * interval + 15, ok_codes=(0, 1))


def build_traceroute(p: dict) -> Command:
    target = check_host(p.get("target"))
    hops = _int(p, "max_hops", 30, 1, 64)
    queries = _int(p, "queries", 3, 1, 5)
    argv = ["traceroute", "-n", "-m", str(hops), "-q", str(queries), "-w", "2"]
    proto = _choice(p, "protocol", "udp", ("udp", "icmp", "tcp"))
    argv += {"udp": [], "icmp": ["-I"], "tcp": ["-T"]}[proto]
    if p.get("ipv6") is True:
        argv.append("-6")
    argv.append(target)
    return Command(argv, timeout=hops * queries * 2 + 15)


def build_mtr(p: dict) -> Command:
    target = check_host(p.get("target"))
    count = _int(p, "count", 10, 1, 200)
    argv = ["mtr", "--json", "-n", "-c", str(count), "-m", str(_int(p, "max_hops", 30, 1, 64))]
    proto = _choice(p, "protocol", "icmp", ("udp", "icmp", "tcp"))
    argv += {"udp": ["-u"], "icmp": [], "tcp": ["-T"]}[proto]
    if p.get("ipv6") is True:
        argv.append("-6")
    argv.append(target)
    return Command(argv, timeout=count * 1.5 + 30)


BUILDERS = {"iperf3": build_iperf3, "ping": build_ping, "traceroute": build_traceroute, "mtr": build_mtr}


async def run_command(cmd: Command) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd.argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=cmd.timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise JobError(f"{cmd.argv[0]} timed out after {cmd.timeout:.0f}s") from None
    return (
        proc.returncode or 0,
        out[:MAX_OUTPUT].decode("utf-8", "replace"),
        err[:10000].decode("utf-8", "replace"),
    )


def _dns_query(p: dict) -> dict:
    name = p.get("name")
    if not isinstance(name, str) or not name or len(name) > 253 or name.startswith("-"):
        raise JobError("invalid name")
    rtype = _choice(p, "record_type", "A", ("A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA", "PTR", "SRV", "CAA"))
    timeout = _float(p, "timeout", 5.0, 0.5, 30.0)
    proto = _choice(p, "protocol", "udp", ("udp", "tcp"))
    server = p.get("server")
    if server:
        server = str(ipaddress.ip_address(server))
    else:
        resolver = dns.resolver.Resolver()
        if not resolver.nameservers:
            raise JobError("no nameserver configured")
        server = str(resolver.nameservers[0])

    try:
        ipaddress.ip_address(name)
        qname = dns.reversename.from_address(name)
        if rtype == "A":
            rtype = "PTR"
    except ValueError:
        stripped = name[:-1] if name.endswith(".") else name
        if not all(_DNS_LABEL.match(l) for l in stripped.split(".")):
            raise JobError("invalid name") from None
        qname = dns.name.from_text(name)

    q = dns.message.make_query(qname, dns.rdatatype.from_text(rtype))
    q.flags |= dns.flags.RD
    start = time.perf_counter()
    try:
        if proto == "tcp":
            resp = dns.query.tcp(q, server, timeout=timeout)
        else:
            resp = dns.query.udp(q, server, timeout=timeout, raise_on_truncation=False)
            if resp.flags & dns.flags.TC:
                resp = dns.query.tcp(q, server, timeout=timeout)
    except dns.exception.Timeout:
        raise JobError(f"DNS query to {server} timed out after {timeout}s") from None
    except OSError as e:
        raise JobError(f"DNS query to {server} failed: {e}") from None
    elapsed = (time.perf_counter() - start) * 1000
    answers = []
    for rrset in resp.answer:
        for rr in rrset:
            answers.append(
                {
                    "name": rrset.name.to_text(),
                    "ttl": rrset.ttl,
                    "type": dns.rdatatype.to_text(rrset.rdtype),
                    "value": rr.to_text(),
                }
            )
    return {
        "name": name,
        "record_type": rtype,
        "server": server,
        "protocol": proto,
        "rcode": dns.rcode.to_text(resp.rcode()),
        "time_ms": round(elapsed, 3),
        "answers": answers,
        "flags": dns.flags.to_text(resp.flags),
    }


async def execute(job_type: str, params: dict) -> dict:
    """Run a job and return the payload for POST /jobs/{id}/result."""
    if not isinstance(params, dict):
        raise JobError("invalid params")
    if job_type == "dns":
        result = await asyncio.to_thread(_dns_query, params)
        return {"status": "completed", "result": result, "raw": None}
    builder = BUILDERS.get(job_type)
    if builder is None:
        raise JobError(f"unsupported job type {job_type!r}")
    cmd = builder(params)
    try:
        code, out, err = await run_command(cmd)
    except FileNotFoundError:
        raise JobError(f"{cmd.argv[0]} is not installed") from None
    if code not in cmd.ok_codes and not out.strip():
        raise JobError(f"{cmd.argv[0]} exited with code {code}: {err.strip()[:2000]}")
    return {"status": "completed", "raw": out if out.strip() else err, "result": None}
