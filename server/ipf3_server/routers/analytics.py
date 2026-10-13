from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import require_admin, require_viewer
from ..models import Agent, AlertEvent, AlertState, AuditLog, Job, JobStatus, JobType, MetricSample, User
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
