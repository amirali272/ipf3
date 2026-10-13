"""Parsers that turn raw tool output reported by agents into structured results.

Parsing lives on the server so the agent stays a thin, auditable executor and so
results are derived from the authoritative raw output, which is also stored."""

from __future__ import annotations

import ipaddress
import json
import re
import statistics
from dataclasses import dataclass, field
from typing import Any


class ParseError(ValueError):
    pass


@dataclass
class Parsed:
    result: dict[str, Any]
    bps: float | None = None
    rtt_avg_ms: float | None = None
    loss_percent: float | None = None
    jitter_ms: float | None = None
    retransmits: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _f(v: Any) -> float | None:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _jitter(rtts: list[float]) -> float | None:
    """Mean absolute difference between consecutive RTT samples (RFC 3550 style,
    without smoothing). Requires at least two samples."""
    if len(rtts) < 2:
        return None
    diffs = [abs(b - a) for a, b in zip(rtts, rtts[1:])]
    return round(sum(diffs) / len(diffs), 3)


# --------------------------------------------------------------------------- iperf3
def parse_iperf3(raw: str) -> Parsed:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ParseError(f"iperf3 output is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ParseError("iperf3 output is not a JSON object")
    if data.get("error"):
        raise ParseError(f"iperf3: {data['error']}")

    start = data.get("start", {}) or {}
    end = data.get("end", {}) or {}
    test = start.get("test_start", {}) or {}
    protocol = (test.get("protocol") or "TCP").lower()
    reverse = bool(test.get("reverse"))
    bidir = bool(test.get("bidir"))
    connected = (start.get("connected") or [{}])[0]

    intervals = []
    reverse_intervals = []
    for itv in data.get("intervals", []) or []:
        s = itv.get("sum") or {}
        if s.get("omitted"):
            continue
        intervals.append(
            {
                "start": _f(s.get("start")),
                "end": _f(s.get("end")),
                "bps": _f(s.get("bits_per_second")),
                "bytes": s.get("bytes"),
                "retransmits": s.get("retransmits"),
                "packets": s.get("packets"),
            }
        )
        sb = itv.get("sum_bidir_reverse")
        if sb:
            reverse_intervals.append(
                {
                    "start": _f(sb.get("start")),
                    "end": _f(sb.get("end")),
                    "bps": _f(sb.get("bits_per_second")),
                    "retransmits": sb.get("retransmits"),
                }
            )

    result: dict[str, Any] = {
        "protocol": protocol,
        "reverse": reverse,
        "bidir": bidir,
        "duration": test.get("duration"),
        "parallel": test.get("num_streams"),
        "version": start.get("version"),
        "local_host": connected.get("local_host"),
        "local_port": connected.get("local_port"),
        "remote_host": connected.get("remote_host"),
        "remote_port": connected.get("remote_port"),
        "tcp_mss": start.get("tcp_mss_default") or start.get("tcp_mss"),
        "intervals": intervals,
        "reverse_intervals": reverse_intervals,
    }
    cpu = end.get("cpu_utilization_percent") or {}
    result["cpu_local_percent"] = _f(cpu.get("host_total"))
    result["cpu_remote_percent"] = _f(cpu.get("remote_total"))

    p = Parsed(result=result)
    if protocol == "tcp":
        sent = end.get("sum_sent") or {}
        recv = end.get("sum_received") or {}
        result["sent_bps"] = _f(sent.get("bits_per_second"))
        result["received_bps"] = _f(recv.get("bits_per_second"))
        result["sent_bytes"] = sent.get("bytes")
        result["received_bytes"] = recv.get("bytes")
        result["retransmits"] = sent.get("retransmits")
        p.bps = result["received_bps"] or result["sent_bps"]
        p.retransmits = sent.get("retransmits")
        if bidir:
            rs = end.get("sum_sent_bidir_reverse") or {}
            rr = end.get("sum_received_bidir_reverse") or {}
            result["reverse_sent_bps"] = _f(rs.get("bits_per_second"))
            result["reverse_received_bps"] = _f(rr.get("bits_per_second"))
            result["reverse_retransmits"] = rs.get("retransmits")
    else:
        recv = end.get("sum_received") or {}
        summ = end.get("sum") or {}
        src = recv if "jitter_ms" in recv else summ
        result["sent_bps"] = _f((end.get("sum_sent") or summ).get("bits_per_second"))
        result["received_bps"] = _f(recv.get("bits_per_second")) if recv else _f(summ.get("bits_per_second"))
        result["jitter_ms"] = _f(src.get("jitter_ms"))
        result["lost_packets"] = src.get("lost_packets")
        result["packets"] = src.get("packets")
        result["lost_percent"] = _f(src.get("lost_percent"))
        result["out_of_order"] = src.get("out_of_order")
        p.bps = result["received_bps"] or result["sent_bps"]
        p.jitter_ms = result["jitter_ms"]
        p.loss_percent = result["lost_percent"]
    if p.bps is None:
        raise ParseError("iperf3 output has no summary (test did not complete)")
    return p


# --------------------------------------------------------------------------- ping
_PING_REPLY = re.compile(
    r"icmp_seq=(?P<seq>\d+)(?:\s+ttl=(?P<ttl>\d+)|\s+hlim=(?P<hlim>\d+))?.*?time[=<](?P<time>[\d.]+)\s*ms"
)
_PING_STATS = re.compile(
    r"(?P<tx>\d+) packets transmitted, (?P<rx>\d+) (?:packets )?received,"
    r"(?: \+(?P<err>\d+) errors,)?(?: \+(?P<dup>\d+) duplicates,)? (?P<loss>[\d.]+)% packet loss"
)
_PING_RTT = re.compile(
    r"(?:rtt|round-trip) min/avg/max/(?:mdev|stddev) = "
    r"(?P<min>[\d.]+)/(?P<avg>[\d.]+)/(?P<max>[\d.]+)/(?P<mdev>[\d.]+) ms"
)
_PING_HEAD = re.compile(r"^PING\s+(?P<host>\S+)\s+\((?P<addr>[^)]+)\)")


def parse_ping(raw: str) -> Parsed:
    replies: list[dict[str, Any]] = []
    seen: set[int] = set()
    stats = rtt = head = None
    for line in raw.splitlines():
        m = _PING_REPLY.search(line)
        if m:
            seq = int(m.group("seq"))
            dup = seq in seen or "DUP!" in line
            seen.add(seq)
            if not dup:
                ttl = m.group("ttl") or m.group("hlim")
                replies.append(
                    {"seq": seq, "ttl": int(ttl) if ttl else None, "rtt_ms": float(m.group("time"))}
                )
            continue
        head = head or _PING_HEAD.match(line)
        stats = stats or _PING_STATS.search(line)
        rtt = rtt or _PING_RTT.search(line)
    if not stats:
        raise ParseError("ping output has no statistics block")
    tx, rx = int(stats.group("tx")), int(stats.group("rx"))
    loss = float(stats.group("loss"))
    rtts = [r["rtt_ms"] for r in sorted(replies, key=lambda r: r["seq"])]
    result: dict[str, Any] = {
        "host": head.group("host") if head else None,
        "address": head.group("addr") if head else None,
        "transmitted": tx,
        "received": rx,
        "errors": int(stats.group("err") or 0),
        "duplicates": int(stats.group("dup") or 0),
        "loss_percent": loss,
        "replies": replies,
    }
    if rtt:
        result.update(
            min_ms=float(rtt.group("min")),
            avg_ms=float(rtt.group("avg")),
            max_ms=float(rtt.group("max")),
            mdev_ms=float(rtt.group("mdev")),
        )
    elif rtts:
        result.update(min_ms=min(rtts), avg_ms=round(statistics.fmean(rtts), 3), max_ms=max(rtts))
    result["jitter_ms"] = _jitter(rtts)
    return Parsed(
        result=result,
        rtt_avg_ms=result.get("avg_ms"),
        loss_percent=loss,
        jitter_ms=result["jitter_ms"],
    )


# --------------------------------------------------------------------------- traceroute
_TR_HOP = re.compile(r"^\s*(\d+)\s+(.*)$")
_TR_TOKEN = re.compile(r"(\*)|([\d.]+)\s*ms|(![A-Za-z0-9<>]*)|(\S+)")


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


def parse_traceroute(raw: str) -> Parsed:
    hops = []
    destination = None
    for line in raw.splitlines():
        if line.startswith("traceroute to"):
            m = re.search(r"\(([^)]+)\)", line)
            destination = m.group(1) if m else None
            continue
        m = _TR_HOP.match(line)
        if not m:
            continue
        hop_no = int(m.group(1))
        probes: list[dict[str, Any]] = []
        addr: str | None = None
        for tm in _TR_TOKEN.finditer(m.group(2)):
            star, ms, flag, word = tm.groups()
            if star:
                probes.append({"address": None, "rtt_ms": None})
            elif ms:
                probes.append({"address": addr, "rtt_ms": float(ms)})
            elif flag and probes:
                probes[-1]["flag"] = flag
            elif word and _is_ip(word.strip("()")):
                addr = word.strip("()")
        rtts = [p["rtt_ms"] for p in probes if p["rtt_ms"] is not None]
        addrs = sorted({p["address"] for p in probes if p["address"]})
        hops.append(
            {
                "hop": hop_no,
                "addresses": addrs,
                "probes": probes,
                "sent": len(probes),
                "lost": len(probes) - len(rtts),
                "loss_percent": round(100.0 * (len(probes) - len(rtts)) / len(probes), 1) if probes else 100.0,
                "min_ms": min(rtts) if rtts else None,
                "avg_ms": round(statistics.fmean(rtts), 3) if rtts else None,
                "max_ms": max(rtts) if rtts else None,
            }
        )
    if not hops:
        raise ParseError("traceroute output has no hops")
    reached = bool(destination and destination in hops[-1]["addresses"])
    result = {"destination": destination, "reached": reached, "hop_count": len(hops), "hops": hops}
    return Parsed(result=result, rtt_avg_ms=hops[-1]["avg_ms"] if reached else None)


# --------------------------------------------------------------------------- mtr
def parse_mtr(raw: str) -> Parsed:
    try:
        data = json.loads(raw)
        report = data["report"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ParseError(f"mtr output is not a valid JSON report: {e}") from e
    meta = report.get("mtr", {}) or {}
    hubs = []
    for h in report.get("hubs", []) or []:
        hubs.append(
            {
                "hop": int(h.get("count", len(hubs) + 1)),
                "host": h.get("host"),
                "loss_percent": _f(h.get("Loss%")),
                "sent": h.get("Snt"),
                "last_ms": _f(h.get("Last")),
                "avg_ms": _f(h.get("Avg")),
                "best_ms": _f(h.get("Best")),
                "worst_ms": _f(h.get("Wrst")),
                "stdev_ms": _f(h.get("StDev")),
            }
        )
    if not hubs:
        raise ParseError("mtr report has no hops")
    last = hubs[-1]
    result = {
        "source": meta.get("src"),
        "destination": meta.get("dst"),
        "tests": _f(meta.get("tests")),
        "packet_size": meta.get("psize"),
        "hops": hubs,
        "reached": last["host"] not in (None, "???"),
    }
    return Parsed(
        result=result,
        rtt_avg_ms=last["avg_ms"],
        loss_percent=last["loss_percent"],
        jitter_ms=last["stdev_ms"],
    )


# --------------------------------------------------------------------------- dns
def parse_dns(result: dict[str, Any] | None) -> Parsed:
    if not isinstance(result, dict):
        raise ParseError("dns result missing")
    time_ms = _f(result.get("time_ms"))
    answers = result.get("answers")
    if not isinstance(answers, list):
        raise ParseError("dns result has no answers list")
    clean = {
        "name": str(result.get("name", ""))[:255],
        "record_type": str(result.get("record_type", ""))[:10],
        "server": result.get("server"),
        "protocol": result.get("protocol"),
        "rcode": str(result.get("rcode", ""))[:32],
        "time_ms": time_ms,
        "answers": [
            {
                "name": str(a.get("name", ""))[:255],
                "ttl": a.get("ttl"),
                "type": str(a.get("type", ""))[:10],
                "value": str(a.get("value", ""))[:1024],
            }
            for a in answers[:500]
            if isinstance(a, dict)
        ],
    }
    return Parsed(result=clean, rtt_avg_ms=time_ms)


def parse_job(job_type: str, raw: str | None, result: dict[str, Any] | None) -> Parsed:
    if job_type == "dns":
        return parse_dns(result)
    if not raw:
        raise ParseError("no output reported")
    return {
        "iperf3": parse_iperf3,
        "ping": parse_ping,
        "traceroute": parse_traceroute,
        "mtr": parse_mtr,
    }[job_type](raw)
