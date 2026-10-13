"""Endpoints used by ipf3-agent. Agents only ever initiate outbound HTTPS
connections to the server (pull model); the server never connects to agents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session, sessionmaker
from ..deps import audit, client_ip, current_agent
from ..models import (
    Agent,
    AgentInventory,
    EnrollmentToken,
    InterfaceSample,
    Job,
    JobStatus,
    LiveRate,
    MetricSample,
    TrafficDaily,
    VpnUser,
    VpnUserTrafficDaily,
    XrayInbound,
    XrayNodeState,
    XrayOutbound,
    XrayRoutingRule,
)
from ..schemas import (
    AgentJobOut,
    EnrollIn,
    EnrollOut,
    HeartbeatIn,
    InventoryIn,
    JobResultIn,
    LiveIn,
    MetricsIn,
)
from ..security import hash_token, random_token
from ..services.parsers import ParseError, parse_job
from ..services.ratelimit import enroll_limiter
from ..services import xray as xray_svc
from ..services.usage import usage_day
from ..vpn_schemas import API_PORT, XrayStateIn, XrayStatsIn

router = APIRouter(prefix="/agent/v1", tags=["agent"])

MAX_CLOCK_SKEW = timedelta(minutes=10)


def _apply_system(agent: Agent, info) -> None:
    agent.hostname = info.hostname
    agent.os_name = info.os_name
    agent.kernel = info.kernel
    agent.agent_version = info.agent_version
    agent.cpu_count = info.cpu_count
    agent.capabilities = info.capabilities


@router.post("/enroll", response_model=EnrollOut, status_code=201)
async def enroll(body: EnrollIn, request: Request, db: AsyncSession = Depends(get_session)):
    if not enroll_limiter.allow(client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many enrollment attempts")
    now = datetime.now(timezone.utc)
    tok = (
        await db.execute(
            select(EnrollmentToken)
            .where(EnrollmentToken.token_hash == hash_token(body.enrollment_token))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if tok is None or tok.used_at is not None or tok.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired enrollment token")
    existing = (await db.execute(select(Agent).where(Agent.name == body.name))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "An agent with this name already exists")

    secret = random_token(32)
    agent = Agent(name=body.name, token_hash=hash_token(secret), last_seen_at=now)
    agent.remote_addr = client_ip(request)[:64]
    _apply_system(agent, body.system)
    db.add(agent)
    await db.flush()
    tok.used_at = now
    tok.agent_id = agent.id
    await audit(db, request, None, "agent.enroll", agent.name, agent_id=agent.id)
    await db.commit()
    return EnrollOut(agent_id=agent.id, agent_token=f"{agent.id}.{secret}")


@router.post("/heartbeat", status_code=204)
async def heartbeat(
    body: HeartbeatIn, agent: Agent = Depends(current_agent), db: AsyncSession = Depends(get_session)
):
    _apply_system(agent, body.system)
    await db.commit()


@router.post("/metrics", status_code=204)
async def metrics(
    body: MetricsIn, agent: Agent = Depends(current_agent), db: AsyncSession = Depends(get_session)
):
    now = datetime.now(timezone.utc)
    ts = body.ts if body.ts.tzinfo else body.ts.replace(tzinfo=timezone.utc)
    if abs(ts - now) > MAX_CLOCK_SKEW:
        # Do not trust a badly skewed agent clock; record at receipt time.
        ts = now
    sys = body.system
    host = _host_interfaces(body.interfaces)
    total_rx = sum(i.rx_bps for i in host)
    total_tx = sum(i.tx_bps for i in host)
    have_bytes = all(i.rx_bytes is not None and i.tx_bytes is not None for i in host) and bool(host)
    rx_bytes = sum(i.rx_bytes or 0 for i in host) if have_bytes else None
    tx_bytes = sum(i.tx_bytes or 0 for i in host) if have_bytes else None
    db.add(
        MetricSample(
            agent_id=agent.id,
            ts=ts,
            rx_bps=total_rx,
            tx_bps=total_tx,
            rx_bytes=rx_bytes,
            tx_bytes=tx_bytes,
            **sys.model_dump(),
        )
    )
    for i in body.interfaces:
        db.add(InterfaceSample(agent_id=agent.id, ts=ts, **i.model_dump()))

    # Accumulate consumption per calendar day (upsert with addition).
    day = usage_day(ts)
    usage_rows = [
        {"agent_id": agent.id, "iface": i.iface, "day": day, "rx_bytes": i.rx_bytes, "tx_bytes": i.tx_bytes}
        for i in body.interfaces
        if i.rx_bytes is not None and i.tx_bytes is not None
    ]
    if have_bytes:
        usage_rows.append({"agent_id": agent.id, "iface": "*", "day": day, "rx_bytes": rx_bytes, "tx_bytes": tx_bytes})
    if usage_rows:
        stmt = pg_insert(TrafficDaily).values(usage_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[TrafficDaily.agent_id, TrafficDaily.iface, TrafficDaily.day],
            set_={
                "rx_bytes": TrafficDaily.rx_bytes + stmt.excluded.rx_bytes,
                "tx_bytes": TrafficDaily.tx_bytes + stmt.excluded.tx_bytes,
            },
        )
        await db.execute(stmt)
    await db.commit()


def _host_interfaces(ifaces: list) -> list:
    """Interfaces counted in the host total: those the agent marks primary
    (device-backed NICs). Older agents send no flag: count everything."""
    flagged = [i for i in ifaces if i.primary is not None]
    if not flagged:
        return list(ifaces)
    primary = [i for i in ifaces if i.primary]
    return primary or list(ifaces)


@router.post("/live", status_code=204)
async def live(body: LiveIn, agent: Agent = Depends(current_agent), db: AsyncSession = Depends(get_session)):
    """Fast (≈2 s) current-rate report for the live view. Not stored as history."""
    host = [i for i in body.interfaces if i.primary] or body.interfaces
    values = {
        "ts": datetime.now(timezone.utc),
        "rx_bps": sum(i.rx_bps for i in host),
        "tx_bps": sum(i.tx_bps for i in host),
        "interfaces": [i.model_dump() for i in body.interfaces],
    }
    stmt = pg_insert(LiveRate).values(agent_id=agent.id, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[LiveRate.agent_id], set_=values)
    await db.execute(stmt)
    await db.commit()


@router.post("/inventory", status_code=204)
async def inventory(
    body: InventoryIn, agent: Agent = Depends(current_agent), db: AsyncSession = Depends(get_session)
):
    values = body.model_dump()
    values["updated_at"] = datetime.now(timezone.utc)
    stmt = pg_insert(AgentInventory).values(agent_id=agent.id, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[AgentInventory.agent_id], set_=values)
    await db.execute(stmt)
    await db.commit()


async def _claim_jobs(agent_id: str, limit: int) -> list[Job]:
    async with sessionmaker()() as db:
        rows = (
            (
                await db.execute(
                    select(Job)
                    .where(Job.agent_id == agent_id, Job.status == JobStatus.queued)
                    .order_by(Job.created_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True, of=Job)
                )
            )
            .unique()
            .scalars()
            .all()
        )
        now = datetime.now(timezone.utc)
        for j in rows:
            j.status = JobStatus.running
            j.started_at = now
        await db.commit()
        return list(rows)


@router.get("/jobs", response_model=list[AgentJobOut])
async def poll_jobs(
    wait: int = Query(0, ge=0, le=25),
    limit: int = Query(4, ge=1, le=16),
    agent: Agent = Depends(current_agent),
    db: AsyncSession = Depends(get_session),
):
    """Long-poll for queued jobs. Returns as soon as at least one job is available
    or after `wait` seconds."""
    await db.commit()  # persist last_seen_at and release the connection
    agent_id = agent.id
    deadline = asyncio.get_running_loop().time() + wait
    while True:
        jobs = await _claim_jobs(agent_id, limit)
        if jobs or asyncio.get_running_loop().time() >= deadline:
            return [AgentJobOut(id=j.id, type=j.type, params=j.params) for j in jobs]
        await asyncio.sleep(1.0)


@router.post("/jobs/{job_id}/result", status_code=204)
async def job_result(
    job_id: str,
    body: JobResultIn,
    agent: Agent = Depends(current_agent),
    db: AsyncSession = Depends(get_session),
):
    job = await db.get(Job, job_id, with_for_update=True)
    if job is None or job.agent_id != agent.id:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.running:
        # Cancelled or expired while running: keep the terminal state.
        await db.commit()
        return
    now = datetime.now(timezone.utc)
    job.finished_at = now
    job.raw = body.raw
    if body.status == "failed":
        job.status = JobStatus.failed
        job.error = body.error or "agent reported failure"
        await db.commit()
        return
    try:
        parsed = parse_job(job.type.value, body.raw, body.result)
    except ParseError as e:
        job.status = JobStatus.failed
        job.error = str(e)[:10000]
        await db.commit()
        return
    job.status = JobStatus.completed
    job.result = parsed.result
    job.bps = parsed.bps
    job.rtt_avg_ms = parsed.rtt_avg_ms
    job.loss_percent = parsed.loss_percent
    job.jitter_ms = parsed.jitter_ms
    job.retransmits = parsed.retransmits
    await db.commit()


# ============================================================================ Xray (VPN)
@router.get("/xray/config")
async def xray_config(
    hash: str | None = Query(None, max_length=64),
    agent: Agent = Depends(current_agent),
    db: AsyncSession = Depends(get_session),
):
    """Desired Xray config for this node. 204 when the agent already has it."""
    from fastapi import Response

    inbounds = (await db.execute(select(XrayInbound).where(XrayInbound.agent_id == agent.id))).scalars().all()
    users = (await db.execute(select(VpnUser))).scalars().all()
    outbounds = [o for o in (await db.execute(select(XrayOutbound))).scalars() if o.on_node(agent.id)]
    rules = (await db.execute(select(XrayRoutingRule))).scalars().all()
    cfg = xray_svc.build_config(inbounds, users, outbounds=outbounds, rules=rules)
    h = xray_svc.config_hash(cfg)
    await db.commit()  # persist last_seen_at
    if hash == h:
        return Response(status_code=204)
    return {"hash": h, "api_port": API_PORT, "config": cfg}


@router.post("/xray/state", status_code=204)
async def xray_state(body: XrayStateIn, agent: Agent = Depends(current_agent), db: AsyncSession = Depends(get_session)):
    now = datetime.now(timezone.utc)
    values = {
        "xray_version": body.version,
        "running": body.running,
        "error": body.error,
        "online_users": body.online_users,
        "online_ips": body.online_ips,
        "updated_at": now,
    }
    if body.applied_hash:
        values["applied_hash"] = body.applied_hash
        values["applied_at"] = now
    stmt = pg_insert(XrayNodeState).values(agent_id=agent.id, **values)
    stmt = stmt.on_conflict_do_update(index_elements=[XrayNodeState.agent_id], set_=values)
    await db.execute(stmt)
    if body.online_users:
        ids = [int(e[1:]) for e in body.online_users if e.startswith("u") and e[1:].isdigit()]
        if ids:
            await db.execute(update(VpnUser).where(VpnUser.id.in_(ids)).values(last_online_at=now))
    await db.commit()


@router.post("/xray/stats", status_code=204)
async def xray_stats(body: XrayStatsIn, agent: Agent = Depends(current_agent), db: AsyncSession = Depends(get_session)):
    """Per-user traffic deltas (bytes) read from Xray's StatsService with reset."""
    now = datetime.now(timezone.utc)
    day = usage_day(now)
    for tag, t in body.outbounds.items():
        if tag.startswith("out-") and tag[4:].isdigit() and (t.up or t.down):
            await db.execute(
                update(XrayOutbound).where(XrayOutbound.id == int(tag[4:])).values(up=XrayOutbound.up + t.up, down=XrayOutbound.down + t.down)
            )
    for tag, t in body.inbounds.items():
        if tag.startswith("in-") and tag[3:].isdigit() and (t.up or t.down):
            await db.execute(
                update(XrayInbound)
                .where(XrayInbound.id == int(tag[3:]), XrayInbound.agent_id == agent.id)
                .values(up=XrayInbound.up + t.up, down=XrayInbound.down + t.down)
            )
    deltas = {}
    for email, t in body.users.items():
        if email.startswith("u") and email[1:].isdigit() and (t.up or t.down):
            deltas[int(email[1:])] = t
    if not deltas:
        await db.commit()
        return
    users = (await db.execute(select(VpnUser).where(VpnUser.id.in_(list(deltas))).with_for_update())).scalars().all()
    rows = []
    for u in users:
        t = deltas[u.id]
        u.used_up += t.up
        u.used_down += t.down
        u.lifetime_used += t.up + t.down
        u.last_online_at = now
        rows.append({"user_id": u.id, "day": day, "up": t.up, "down": t.down})
    if rows:
        stmt = pg_insert(VpnUserTrafficDaily).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[VpnUserTrafficDaily.user_id, VpnUserTrafficDaily.day],
            set_={"up": VpnUserTrafficDaily.up + stmt.excluded.up, "down": VpnUserTrafficDaily.down + stmt.excluded.down},
        )
        await db.execute(stmt)
    await db.commit()
