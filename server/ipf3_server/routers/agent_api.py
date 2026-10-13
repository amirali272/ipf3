"""Endpoints used by ipf3-agent. Agents only ever initiate outbound HTTPS
connections to the server (pull model); the server never connects to agents."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
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
    MetricSample,
)
from ..schemas import (
    AgentJobOut,
    EnrollIn,
    EnrollOut,
    HeartbeatIn,
    InventoryIn,
    JobResultIn,
    MetricsIn,
)
from ..security import hash_token, random_token
from ..services.parsers import ParseError, parse_job
from ..services.ratelimit import enroll_limiter

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
    total_rx = sum(i.rx_bps for i in body.interfaces)
    total_tx = sum(i.tx_bps for i in body.interfaces)
    db.add(
        MetricSample(
            agent_id=agent.id,
            ts=ts,
            rx_bps=total_rx,
            tx_bps=total_tx,
            **sys.model_dump(),
        )
    )
    for i in body.interfaces:
        db.add(InterfaceSample(agent_id=agent.id, ts=ts, **i.model_dump()))
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
