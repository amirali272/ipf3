"""Background worker: schedules -> jobs, job expiry, alert evaluation, retention.

Runs as its own systemd unit (ipf3-worker). A PostgreSQL advisory lock ensures
only one worker is active even if several are started by mistake."""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text, update

from .config import get_settings
from .db import dispose_engine, get_engine, sessionmaker
from .models import (
    Agent,
    AlertEvent,
    AlertState,
    AuditLog,
    EnrollmentToken,
    InterfaceSample,
    Job,
    JobStatus,
    MetricSample,
    Schedule,
    TrafficDaily,
)
from .schemas import job_target
from .services import alerting

log = logging.getLogger("ipf3.worker")

ADVISORY_LOCK_KEY = 0x1BF3_0001


async def run_schedules(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    created = 0
    async with sessionmaker()() as db:
        schedules = (
            (
                await db.execute(
                    select(Schedule)
                    .join(Agent, Agent.id == Schedule.agent_id)
                    .where(Schedule.enabled, Agent.disabled.is_(False))
                    .with_for_update(of=Schedule, skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        for s in schedules:
            if s.last_run_at and (now - s.last_run_at).total_seconds() < s.interval_seconds:
                continue
            # Never stack runs: skip while a previous run is still pending.
            pending = (
                await db.execute(
                    select(Job.id)
                    .where(Job.schedule_id == s.id, Job.status.in_([JobStatus.queued, JobStatus.running]))
                    .limit(1)
                )
            ).first()
            if pending:
                continue
            db.add(
                Job(
                    agent_id=s.agent_id,
                    type=s.type,
                    params=s.params,
                    target=job_target(s.type, s.params),
                    schedule_id=s.id,
                )
            )
            s.last_run_at = now
            created += 1
        await db.commit()
    return created


async def expire_jobs(now: datetime | None = None) -> int:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    async with sessionmaker()() as db:
        r1 = await db.execute(
            update(Job)
            .where(
                Job.status == JobStatus.queued,
                Job.created_at < now - timedelta(seconds=s.job_queued_timeout_seconds),
            )
            .values(status=JobStatus.expired, finished_at=now, error="agent did not pick up the job in time")
        )
        r2 = await db.execute(
            update(Job)
            .where(
                Job.status == JobStatus.running,
                Job.started_at < now - timedelta(seconds=s.job_running_timeout_seconds),
            )
            .values(status=JobStatus.expired, finished_at=now, error="agent did not report a result in time")
        )
        await db.commit()
        return (r1.rowcount or 0) + (r2.rowcount or 0)


async def evaluate_alerts(now: datetime | None = None) -> int:
    async with sessionmaker()() as db:
        transitions = await alerting.evaluate(db, now)
        names = dict((await db.execute(select(Agent.id, Agent.name))).all())
    if transitions:
        await alerting.notify(transitions, names)
    return len(transitions)


async def purge_old_data(now: datetime | None = None) -> dict[str, int]:
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    out = {}
    async with sessionmaker()() as db:
        for name, model, col, days in (
            ("metric_samples", MetricSample, MetricSample.ts, s.retention_metrics_days),
            ("interface_samples", InterfaceSample, InterfaceSample.ts, s.retention_metrics_days),
            ("jobs", Job, Job.created_at, s.retention_jobs_days),
            ("audit_log", AuditLog, AuditLog.ts, s.retention_audit_days),
        ):
            r = await db.execute(delete(model).where(col < now - timedelta(days=days)))
            out[name] = r.rowcount or 0
        r = await db.execute(
            delete(AlertEvent).where(
                AlertEvent.state == AlertState.resolved,
                AlertEvent.resolved_at < now - timedelta(days=s.retention_alerts_days),
            )
        )
        out["alert_events"] = r.rowcount or 0
        r = await db.execute(
            delete(TrafficDaily).where(TrafficDaily.day < (now - timedelta(days=s.retention_usage_days)).date())
        )
        out["traffic_daily"] = r.rowcount or 0
        r = await db.execute(
            delete(EnrollmentToken).where(EnrollmentToken.expires_at < now - timedelta(days=30))
        )
        out["enrollment_tokens"] = r.rowcount or 0
        await db.commit()
    return out


async def _loop(name: str, interval: float, fn, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            result = await fn()
            if result:
                log.info("%s: %s", name, result)
        except Exception:  # noqa: BLE001 - keep the worker alive, log the failure
            log.exception("%s failed", name)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    engine = get_engine()
    lock_conn = await engine.connect()
    while not stop.is_set():
        got = (await lock_conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})).scalar()
        await lock_conn.commit()  # session-level lock survives; avoid idle-in-transaction
        if got:
            break
        log.info("another worker holds the lock; waiting")
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except asyncio.TimeoutError:
            pass
    if stop.is_set():
        await lock_conn.close()
        await dispose_engine()
        return
    log.info("worker started")

    async def schedules_and_expiry():
        a = await run_schedules()
        b = await expire_jobs()
        return {"scheduled": a, "expired": b} if a or b else None

    try:
        await asyncio.gather(
            _loop("scheduler", s.scheduler_interval, schedules_and_expiry, stop),
            _loop("alerts", s.alert_interval, evaluate_alerts, stop),
            _loop("retention", s.retention_interval, purge_old_data, stop),
        )
    finally:
        await lock_conn.close()
        await dispose_engine()
        log.info("worker stopped")


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
