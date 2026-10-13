from __future__ import annotations

import asyncio
import logging
import operator as op
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import (
    Agent,
    AlertEvent,
    AlertRule,
    AlertState,
    InterfaceSample,
    Job,
    JobStatus,
    JobType,
    MetricSample,
)

log = logging.getLogger("ipf3.alerts")

OPS = {">": op.gt, ">=": op.ge, "<": op.lt, "<=": op.le, "==": op.eq}

SYSTEM_METRICS = {"cpu_percent", "mem_percent", "disk_percent", "load1"}
TEST_METRICS = {
    "ping_loss_percent": (JobType.ping, Job.loss_percent),
    "ping_rtt_ms": (JobType.ping, Job.rtt_avg_ms),
    "ping_jitter_ms": (JobType.ping, Job.jitter_ms),
    "iperf3_bps": (JobType.iperf3, Job.bps),
    "iperf3_loss_percent": (JobType.iperf3, Job.loss_percent),
    "dns_time_ms": (JobType.dns, Job.rtt_avg_ms),
}
TEST_MIN_WINDOW = 900  # seconds; scheduled tests are sparse


def _sustained_agg(operator: str, column):
    """For "greater than" style rules the condition must hold for every sample in
    the window, i.e. the minimum must exceed the threshold (and vice versa)."""
    if operator in (">", ">="):
        return func.min(column)
    if operator in ("<", "<="):
        return func.max(column)
    return func.avg(column)


async def compute_value(db: AsyncSession, rule: AlertRule, agent: Agent, now: datetime) -> float | None:
    window = timedelta(seconds=max(rule.for_seconds, 30))
    since = now - window

    if rule.metric == "agent_offline":
        ref = agent.last_seen_at or agent.created_at
        return round((now - ref).total_seconds(), 1)

    if rule.metric in SYSTEM_METRICS:
        col = getattr(MetricSample, rule.metric)
        q = select(_sustained_agg(rule.operator, col), func.count(col)).where(
            MetricSample.agent_id == agent.id, MetricSample.ts >= since
        )
        val, n = (await db.execute(q)).one()
        return None if not n else float(val)

    if rule.metric in ("iface_rx_bps", "iface_tx_bps"):
        field = rule.metric.removeprefix("iface_")
        if rule.iface:
            col = getattr(InterfaceSample, field)
            q = select(_sustained_agg(rule.operator, col), func.count(col)).where(
                InterfaceSample.agent_id == agent.id,
                InterfaceSample.iface == rule.iface,
                InterfaceSample.ts >= since,
            )
        else:
            col = getattr(MetricSample, field)
            q = select(_sustained_agg(rule.operator, col), func.count(col)).where(
                MetricSample.agent_id == agent.id, MetricSample.ts >= since
            )
        val, n = (await db.execute(q)).one()
        return None if not n else float(val)

    if rule.metric == "iface_errors":
        q = select(
            func.sum(
                InterfaceSample.rx_errs
                + InterfaceSample.tx_errs
                + InterfaceSample.rx_drops
                + InterfaceSample.tx_drops
            ),
            func.count(InterfaceSample.id),
        ).where(InterfaceSample.agent_id == agent.id, InterfaceSample.ts >= since)
        if rule.iface:
            q = q.where(InterfaceSample.iface == rule.iface)
        val, n = (await db.execute(q)).one()
        return None if not n else float(val or 0)

    test_since = now - timedelta(seconds=max(rule.for_seconds, TEST_MIN_WINDOW))
    if rule.metric in TEST_METRICS:
        jtype, col = TEST_METRICS[rule.metric]
        q = select(func.avg(col), func.count(col)).where(
            Job.agent_id == agent.id,
            Job.type == jtype,
            Job.status == JobStatus.completed,
            Job.finished_at >= test_since,
        )
        if rule.target:
            q = q.where(Job.target == rule.target)
        val, n = (await db.execute(q)).one()
        return None if not n else float(val)

    if rule.metric == "job_failed":
        q = select(func.count(Job.id)).where(
            Job.agent_id == agent.id,
            Job.schedule_id.is_not(None),
            Job.status.in_([JobStatus.failed, JobStatus.expired]),
            Job.finished_at >= test_since,
        )
        if rule.target:
            q = q.where(Job.target == rule.target)
        return float((await db.execute(q)).scalar_one())

    return None


def _fmt(metric: str, value: float) -> str:
    if metric.endswith("_bps"):
        for unit, div in (("Gbit/s", 1e9), ("Mbit/s", 1e6), ("kbit/s", 1e3)):
            if abs(value) >= div:
                return f"{value / div:.2f} {unit}"
        return f"{value:.0f} bit/s"
    return f"{value:.2f}"


async def evaluate(db: AsyncSession, now: datetime | None = None) -> list[tuple[AlertEvent, str]]:
    """Evaluate all enabled rules. Returns (event, transition) pairs to notify."""
    now = now or datetime.now(timezone.utc)
    rules = (await db.execute(select(AlertRule).where(AlertRule.enabled))).scalars().all()
    agents = (await db.execute(select(Agent).where(Agent.disabled.is_(False)))).scalars().all()
    open_events = {
        (e.rule_id, e.agent_id): e
        for e in (
            await db.execute(select(AlertEvent).where(AlertEvent.state == AlertState.firing))
        ).scalars()
    }
    transitions: list[tuple[AlertEvent, str]] = []
    for rule in rules:
        scope = [a for a in agents if rule.agent_id in (None, a.id)]
        for agent in scope:
            value = await compute_value(db, rule, agent, now)
            existing = open_events.get((rule.id, agent.id))
            firing = value is not None and OPS[rule.operator](value, rule.threshold)
            if firing and existing is None:
                ev = AlertEvent(
                    rule_id=rule.id,
                    agent_id=agent.id,
                    state=AlertState.firing,
                    severity=rule.severity,
                    value=value,
                    started_at=now,
                    message=(
                        f"{rule.name}: {rule.metric} on {agent.name} is {_fmt(rule.metric, value)} "
                        f"({rule.operator} {_fmt(rule.metric, rule.threshold)})"
                    ),
                )
                ev.rule = rule
                db.add(ev)
                transitions.append((ev, "firing"))
            elif firing and existing is not None:
                existing.value = value
            elif not firing and existing is not None and (value is not None or rule.metric == "agent_offline"):
                existing.state = AlertState.resolved
                existing.resolved_at = now
                existing.value = value
                transitions.append((existing, "resolved"))
    # Close events for rules that were disabled/deleted or agents now out of scope.
    active_keys = {(r.id, a.id) for r in rules for a in agents if r.agent_id in (None, a.id)}
    for key, ev in open_events.items():
        if key not in active_keys:
            ev.state = AlertState.resolved
            ev.resolved_at = now
    await db.commit()
    return transitions


# --------------------------------------------------------------------------- notify
def _payload(ev: AlertEvent, transition: str, agent_name: str | None) -> dict:
    rule = ev.rule
    status = "FIRING" if transition == "firing" else "RESOLVED"
    text = f"[{status}] [{ev.severity.value.upper()}] {ev.message}"
    return {
        "text": text,  # Slack / Mattermost / Teams-compatible
        "status": transition,
        "severity": ev.severity.value,
        "rule": {"id": rule.id, "name": rule.name, "metric": rule.metric, "operator": rule.operator, "threshold": rule.threshold},
        "agent": {"id": ev.agent_id, "name": agent_name},
        "value": ev.value,
        "message": ev.message,
        "started_at": ev.started_at.isoformat() if ev.started_at else None,
        "resolved_at": ev.resolved_at.isoformat() if ev.resolved_at else None,
        "event_id": ev.id,
    }


def _send_email(to: list[str], subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as smtp:
        if s.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if s.smtp_user:
            smtp.login(s.smtp_user, s.smtp_password)
        smtp.send_message(msg)


async def notify(transitions: list[tuple[AlertEvent, str]], agent_names: dict[str, str]) -> None:
    s = get_settings()
    async with httpx.AsyncClient(timeout=s.webhook_timeout_seconds, follow_redirects=False) as client:
        for ev, transition in transitions:
            rule = ev.rule
            payload = _payload(ev, transition, agent_names.get(ev.agent_id or ""))
            if rule.webhook_url:
                try:
                    r = await client.post(rule.webhook_url, json=payload)
                    if r.status_code >= 400:
                        log.warning("webhook for rule %s returned HTTP %s", rule.id, r.status_code)
                except httpx.HTTPError as e:
                    log.warning("webhook for rule %s failed: %s", rule.id, e)
            if rule.email_to and s.smtp_host:
                try:
                    await asyncio.to_thread(
                        _send_email,
                        rule.email_to.split(","),
                        payload["text"][:200],
                        payload["text"] + "\n\n" + "\n".join(f"{k}: {v}" for k, v in payload.items() if k != "text"),
                    )
                except (OSError, smtplib.SMTPException) as e:
                    log.warning("email for rule %s failed: %s", rule.id, e)
