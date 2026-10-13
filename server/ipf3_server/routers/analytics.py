from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import require_admin, require_viewer
from ..models import (
    Agent,
    AlertEvent,
    AlertState,
    AuditLog,
    Job,
    JobStatus,
    JobType,
    LiveRate,
    MetricSample,
    TrafficDaily,
    User,
)
from ..services import usage
from ..schemas import AuditOut
from ..services.timeseries import bucket_expr, pick_bucket, resolve_range
from .agents import is_online, latest_metrics

router = APIRouter(tags=["analytics"])


@router.get("/analytics/overview")
async def overview(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    agents = (await db.execute(select(Agent))).scalars().all()
    latest = await latest_metrics(db)
    online = [a for a in agents if is_online(a, now)]
    firing = (
        await db.execute(
            select(AlertEvent.severity, func.count())
            .where(AlertEvent.state == AlertState.firing)
            .group_by(AlertEvent.severity)
        )
    ).all()
    jobs = (
        await db.execute(
            select(Job.status, func.count())
            .where(Job.created_at >= now - timedelta(hours=24))
            .group_by(Job.status)
        )
    ).all()
    online_ids = {a.id for a in online}
    return {
        "agents_total": len(agents),
        "agents_online": len(online),
        "agents_disabled": sum(1 for a in agents if a.disabled),
        "alerts_firing": {s.value: n for s, n in firing},
        "jobs_24h": {s.value: n for s, n in jobs},
        "fleet_rx_bps": sum((latest[i].get("rx_bps") or 0) for i in latest if i in online_ids),
        "fleet_tx_bps": sum((latest[i].get("tx_bps") or 0) for i in latest if i in online_ids),
        "generated_at": now,
    }


@router.get("/analytics/tests")
async def test_series(
    type: JobType,
    agent_id: str | None = None,
    target: str | None = None,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    bucket: int | None = Query(None, ge=60, le=86400),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    start, end = resolve_range(start, end, default=timedelta(days=1))
    b = max(60, pick_bucket(start, end, bucket, points=200))
    t = bucket_expr(Job.finished_at, b).label("t")
    q = (
        select(
            t,
            func.count(Job.id).label("count"),
            func.avg(Job.bps).label("bps_avg"),
            func.min(Job.bps).label("bps_min"),
            func.max(Job.bps).label("bps_max"),
            func.avg(Job.rtt_avg_ms).label("rtt_avg_ms"),
            func.max(Job.rtt_avg_ms).label("rtt_max_ms"),
            func.avg(Job.loss_percent).label("loss_percent"),
            func.avg(Job.jitter_ms).label("jitter_ms"),
            func.sum(Job.retransmits).label("retransmits"),
        )
        .where(
            Job.type == type,
            Job.status == JobStatus.completed,
            Job.finished_at >= start,
            Job.finished_at < end,
        )
        .group_by(t)
        .order_by(t)
    )
    if agent_id:
        q = q.where(Job.agent_id == agent_id)
    if target:
        q = q.where(Job.target == target)
    rows = (await db.execute(q)).mappings().all()

    stats_q = select(
        func.count(Job.id),
        func.avg(Job.bps),
        func.percentile_cont(0.95).within_group(Job.rtt_avg_ms),
        func.avg(Job.rtt_avg_ms),
        func.avg(Job.loss_percent),
        func.avg(Job.jitter_ms),
    ).where(
        Job.type == type,
        Job.status == JobStatus.completed,
        Job.finished_at >= start,
        Job.finished_at < end,
    )
    failed_q = select(func.count(Job.id)).where(
        Job.type == type,
        Job.status.in_([JobStatus.failed, JobStatus.expired]),
        Job.created_at >= start,
        Job.created_at < end,
    )
    if agent_id:
        stats_q = stats_q.where(Job.agent_id == agent_id)
        failed_q = failed_q.where(Job.agent_id == agent_id)
    if target:
        stats_q = stats_q.where(Job.target == target)
        failed_q = failed_q.where(Job.target == target)
    n, bps, rtt_p95, rtt, loss, jitter = (await db.execute(stats_q)).one()
    failed = (await db.execute(failed_q)).scalar_one()
    return {
        "bucket": b,
        "from": start,
        "to": end,
        "summary": {
            "completed": n,
            "failed": failed,
            "bps_avg": bps,
            "rtt_avg_ms": rtt,
            "rtt_p95_ms": rtt_p95,
            "loss_percent": loss,
            "jitter_ms": jitter,
        },
        "points": [dict(r) for r in rows],
    }


@router.get("/analytics/targets")
async def test_targets(
    days: int = Query(30, ge=1, le=400),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(Job.agent_id, Job.type, Job.target, func.count(Job.id), func.max(Job.created_at))
            .where(Job.created_at >= since)
            .group_by(Job.agent_id, Job.type, Job.target)
            .order_by(func.max(Job.created_at).desc())
            .limit(500)
        )
    ).all()
    return [
        {"agent_id": a, "type": t.value, "target": tg, "count": c, "last": last}
        for a, t, tg, c, last in rows
    ]


@router.get("/analytics/fleet")
async def fleet(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    start, end = resolve_range(start, end, default=timedelta(days=1))
    rows = (
        await db.execute(
            select(
                MetricSample.agent_id,
                Agent.name,
                func.avg(MetricSample.cpu_percent).label("cpu_avg"),
                func.max(MetricSample.cpu_percent).label("cpu_max"),
                func.avg(MetricSample.mem_percent).label("mem_avg"),
                func.avg(MetricSample.rx_bps).label("rx_avg"),
                func.max(MetricSample.rx_bps).label("rx_max"),
                func.avg(MetricSample.tx_bps).label("tx_avg"),
                func.max(MetricSample.tx_bps).label("tx_max"),
                func.count(MetricSample.id).label("samples"),
            )
            .join(Agent, Agent.id == MetricSample.agent_id)
            .where(MetricSample.ts >= start, MetricSample.ts < end)
            .group_by(MetricSample.agent_id, Agent.name)
            .order_by(Agent.name)
        )
    ).mappings().all()
    return {"from": start, "to": end, "agents": [dict(r) for r in rows]}


@router.get("/audit", response_model=list[AuditOut])
async def audit_log(
    action: str | None = None,
    username: str | None = None,
    before_id: int | None = None,
    limit: int = Query(100, ge=1, le=1000),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        q = q.where(AuditLog.action.startswith(action))
    if username:
        q = q.where(AuditLog.username == username)
    if before_id:
        q = q.where(AuditLog.id < before_id)
    return (await db.execute(q)).scalars().all()


# --------------------------------------------------------------------------- traffic usage
@router.get("/analytics/usage")
async def traffic_usage(
    days: int = Query(30, ge=1, le=1095),
    agent_id: str | None = None,
    iface: str = Query("*", max_length=64),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    """Bytes actually transferred (from kernel counters) per day and month.
    iface '*' = host total over primary (device-backed) interfaces."""
    t = usage.today()
    m = usage.month_start(t)
    since = min(usage.days_back(t, days - 1), m)

    rows = (
        await db.execute(
            select(TrafficDaily.agent_id, TrafficDaily.day, TrafficDaily.rx_bytes, TrafficDaily.tx_bytes)
            .where(TrafficDaily.iface == iface, TrafficDaily.day >= since)
            .where(TrafficDaily.agent_id == agent_id if agent_id else True)
        )
    ).all()
    names = dict((await db.execute(select(Agent.id, Agent.name))).all())

    per_agent: dict[str, dict] = {}
    daily: dict = {}
    for aid, day, rx, tx in rows:
        a = per_agent.setdefault(aid, {"agent_id": aid, "name": names.get(aid, aid), "today_rx": 0, "today_tx": 0, "month_rx": 0, "month_tx": 0, "period_rx": 0, "period_tx": 0})
        if day == t:
            a["today_rx"] += rx
            a["today_tx"] += tx
        if day >= m:
            a["month_rx"] += rx
            a["month_tx"] += tx
        if day >= usage.days_back(t, days - 1):
            a["period_rx"] += rx
            a["period_tx"] += tx
            d = daily.setdefault(day, {"day": day, "rx_bytes": 0, "tx_bytes": 0})
            d["rx_bytes"] += rx
            d["tx_bytes"] += tx
    # One entry per day from the first recorded day in the period up to today.
    # Days before anything was recorded are omitted rather than shown as 0 bytes;
    # later days without reports (agent down) are 0 because nothing was measured.
    series = []
    if daily:
        first = min(daily)
        n_days = (t - first).days
        for n in range(n_days, -1, -1):
            d = usage.days_back(t, n)
            series.append(daily.get(d, {"day": d, "rx_bytes": 0, "tx_bytes": 0}))
    agents = sorted(per_agent.values(), key=lambda a: -(a["today_rx"] + a["today_tx"]))
    fleet = {k: sum(a[k] for a in agents) for k in ("today_rx", "today_tx", "month_rx", "month_tx", "period_rx", "period_tx")}
    return {
        "timezone": str(usage.usage_tz()),
        "today": t,
        "month_start": m,
        "days": days,
        "fleet": fleet,
        "agents": agents,
        "daily": series,
    }


@router.get("/analytics/fleet-bandwidth")
async def fleet_bandwidth(
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    bucket: int | None = Query(None, ge=10, le=86400),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    """Fleet-wide rx/tx: per bucket, average each agent's samples, then sum agents."""
    start, end = resolve_range(start, end, default=timedelta(hours=1))
    b = pick_bucket(start, end, bucket)
    t = bucket_expr(MetricSample.ts, b).label("t")
    per_agent = (
        select(
            t,
            MetricSample.agent_id,
            func.avg(MetricSample.rx_bps).label("rx"),
            func.avg(MetricSample.tx_bps).label("tx"),
            func.sum(MetricSample.rx_bytes).label("rxb"),
            func.sum(MetricSample.tx_bytes).label("txb"),
        )
        .where(MetricSample.ts >= start, MetricSample.ts < end)
        .group_by(t, MetricSample.agent_id)
        .subquery()
    )
    q = (
        select(
            per_agent.c.t,
            func.sum(per_agent.c.rx).label("rx_bps"),
            func.sum(per_agent.c.tx).label("tx_bps"),
            func.sum(per_agent.c.rxb).label("rx_bytes"),
            func.sum(per_agent.c.txb).label("tx_bytes"),
        )
        .group_by(per_agent.c.t)
        .order_by(per_agent.c.t)
    )
    rows = (await db.execute(q)).mappings().all()
    return {"bucket": b, "from": start, "to": end, "points": [dict(r) for r in rows]}


@router.get("/analytics/live")
async def live_rates(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    """Latest ≈2 s rate sample per agent (current consumption)."""
    fresh = datetime.now(timezone.utc) - timedelta(seconds=15)
    rows = (await db.execute(select(LiveRate).where(LiveRate.ts >= fresh))).scalars().all()
    return [
        {"agent_id": r.agent_id, "ts": r.ts, "rx_bps": r.rx_bps, "tx_bps": r.tx_bps, "interfaces": r.interfaces}
        for r in rows
    ]


# --------------------------------------------------------------------------- control-plane status
def _read_cpu_times() -> tuple[int, int] | None:
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()[1:]
        vals = [int(x) for x in parts]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return sum(vals), idle
    except (OSError, ValueError, IndexError):
        return None


def _mem_percent() -> float | None:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                info[k] = int(v.split()[0])
        total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
        return round(100.0 * (total - avail) / total, 1) if total else None
    except (OSError, KeyError, ValueError):
        return None


@router.get("/system/status")
async def system_status(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    """Health of the control plane itself: API, database, worker and host load."""
    import asyncio
    import shutil

    from .. import __version__
    from ..worker import ADVISORY_LOCK_KEY

    a = _read_cpu_times()
    await asyncio.sleep(0.25)
    b = _read_cpu_times()
    cpu = None
    if a and b and b[0] > a[0]:
        cpu = round(100.0 * (1 - (b[1] - a[1]) / (b[0] - a[0])), 1)
    try:
        du = shutil.disk_usage("/")
        disk = round(100.0 * du.used / du.total, 1)
    except OSError:
        disk = None
    worker = (
        await db.execute(
            text(
                "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND granted "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database()) "
                "AND ((classid::bigint << 32) | objid::bigint) = :k"
            ),
            {"k": ADVISORY_LOCK_KEY},
        )
    ).scalar_one()
    return {
        "version": __version__,
        "api": True,
        "database": True,
        "worker": worker > 0,
        "cpu_percent": cpu,
        "mem_percent": _mem_percent(),
        "disk_percent": disk,
        "usage_timezone": str(usage.usage_tz()),
    }
