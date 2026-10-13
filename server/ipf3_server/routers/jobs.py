from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import audit, require_operator, require_viewer
from ..models import Agent, Job, JobStatus, JobType, Schedule, User
from ..schemas import (
    JobCreate,
    JobDetailOut,
    JobOut,
    ScheduleCreate,
    ScheduleOut,
    ScheduleUpdate,
    job_target,
    validate_job_params,
)

router = APIRouter(tags=["jobs"])

# Per-agent concurrency guard: refuse to pile up unbounded manual work.
MAX_QUEUED_PER_AGENT = 50


def _params_or_422(job_type: JobType, params: dict) -> dict:
    try:
        return validate_job_params(job_type, params)
    except ValidationError as e:
        raise HTTPException(
            422, [{"loc": ["params", *err["loc"]], "msg": err["msg"]} for err in e.errors()]
        ) from e


def check_capability(agent: Agent, job_type: JobType) -> None:
    caps = agent.capabilities or {}
    tools = caps.get("tools") or {}
    if tools and not tools.get(job_type.value, False):
        raise HTTPException(
            409, f"Agent '{agent.name}' reports that {job_type.value} is not installed"
        )


def job_out(job: Job, detail: bool = False) -> JobOut:
    cls = JobDetailOut if detail else JobOut
    out = cls.model_validate(job)
    out.agent_name = job.agent.name if job.agent else None
    return out


@router.post("/jobs", response_model=JobOut, status_code=201)
async def create_job(
    body: JobCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
):
    agent = await db.get(Agent, body.agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    if agent.disabled:
        raise HTTPException(409, "Agent is disabled")
    check_capability(agent, body.type)
    params = _params_or_422(body.type, body.params)
    queued = (
        await db.execute(
            select(Job.id).where(Job.agent_id == agent.id, Job.status == JobStatus.queued).limit(
                MAX_QUEUED_PER_AGENT
            )
        )
    ).all()
    if len(queued) >= MAX_QUEUED_PER_AGENT:
        raise HTTPException(429, "Too many queued jobs for this agent")
    job = Job(
        agent_id=agent.id,
        type=body.type,
        params=params,
        target=job_target(body.type, params),
        created_by=user.id,
    )
    db.add(job)
    await db.flush()
    await audit(db, request, user, "job.create", f"{body.type.value} {job.target}", job_id=job.id, agent=agent.name)
    await db.commit()
    await db.refresh(job, ["agent"])
    return job_out(job)


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    agent_id: str | None = None,
    type: JobType | None = None,
    status: JobStatus | None = None,
    schedule_id: int | None = None,
    target: str | None = None,
    before: datetime | None = None,
    limit: int = Query(50, ge=1, le=500),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    q = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if agent_id:
        q = q.where(Job.agent_id == agent_id)
    if type:
        q = q.where(Job.type == type)
    if status:
        q = q.where(Job.status == status)
    if schedule_id:
        q = q.where(Job.schedule_id == schedule_id)
    if target:
        q = q.where(Job.target == target)
    if before:
        q = q.where(Job.created_at < before)
    rows = (await db.execute(q)).scalars().all()
    return [job_out(j) for j in rows]


@router.get("/jobs/{job_id}", response_model=JobDetailOut)
async def get_job(job_id: str, _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job_out(job, detail=True)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
async def cancel_job(
    job_id: str,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
):
    job = await db.get(Job, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(404, "Job not found")
    if job.status not in (JobStatus.queued, JobStatus.running):
        raise HTTPException(409, f"Job is already {job.status.value}")
    job.status = JobStatus.cancelled
    job.finished_at = datetime.now(timezone.utc)
    await audit(db, request, user, "job.cancel", job.id)
    await db.commit()
    return job_out(job)


# --------------------------------------------------------------------------- schedules
@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    return (await db.execute(select(Schedule).order_by(Schedule.name))).scalars().all()


@router.post("/schedules", response_model=ScheduleOut, status_code=201)
async def create_schedule(
    body: ScheduleCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
):
    agent = await db.get(Agent, body.agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    check_capability(agent, body.type)
    params = _params_or_422(body.type, body.params)
    if body.type == JobType.iperf3 and body.interval_seconds < 300:
        raise HTTPException(422, "Scheduled iperf3 tests must run at most every 5 minutes")
    sched = Schedule(
        name=body.name,
        agent_id=agent.id,
        type=body.type,
        params=params,
        interval_seconds=body.interval_seconds,
        enabled=body.enabled,
        created_by=user.id,
    )
    db.add(sched)
    await db.flush()
    await audit(db, request, user, "schedule.create", sched.name, schedule_id=sched.id)
    await db.commit()
    return sched


@router.patch("/schedules/{schedule_id}", response_model=ScheduleOut)
async def update_schedule(
    schedule_id: int,
    body: ScheduleUpdate,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
):
    sched = await db.get(Schedule, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    changes = body.model_dump(exclude_unset=True)
    if "params" in changes:
        changes["params"] = _params_or_422(sched.type, changes["params"])
    interval = changes.get("interval_seconds", sched.interval_seconds)
    if sched.type == JobType.iperf3 and interval < 300:
        raise HTTPException(422, "Scheduled iperf3 tests must run at most every 5 minutes")
    for k, v in changes.items():
        setattr(sched, k, v)
    await audit(db, request, user, "schedule.update", sched.name, **{k: v for k, v in changes.items() if k != "params"})
    await db.commit()
    return sched


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
):
    sched = await db.get(Schedule, schedule_id)
    if sched is None:
        raise HTTPException(404, "Schedule not found")
    await audit(db, request, user, "schedule.delete", sched.name)
    await db.delete(sched)
    await db.commit()
