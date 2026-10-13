from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import audit, require_admin, require_operator, require_viewer
from ..models import Agent, AlertEvent, AlertRule, AlertState, User
from ..schemas import (
    ALERT_METRICS,
    AlertEventOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
)

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("/metrics")
async def alert_metrics(_: User = Depends(require_viewer)):
    return ALERT_METRICS


@router.get("/rules", response_model=list[AlertRuleOut])
async def list_rules(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    return (await db.execute(select(AlertRule).order_by(AlertRule.name))).scalars().all()


async def _check_agent(db: AsyncSession, agent_id: str | None) -> None:
    if agent_id and await db.get(Agent, agent_id) is None:
        raise HTTPException(404, "Agent not found")


@router.post("/rules", response_model=AlertRuleOut, status_code=201)
async def create_rule(
    body: AlertRuleCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    await _check_agent(db, body.agent_id)
    rule = AlertRule(**body.model_dump())
    db.add(rule)
    await db.flush()
    await audit(db, request, admin, "alert_rule.create", rule.name, rule_id=rule.id)
    await db.commit()
    return rule


@router.patch("/rules/{rule_id}", response_model=AlertRuleOut)
async def update_rule(
    rule_id: int,
    body: AlertRuleUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    rule = await db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    changes = body.model_dump(exclude_unset=True)
    if "agent_id" in changes:
        await _check_agent(db, changes["agent_id"])
    for k, v in changes.items():
        if v is None and k in {"name", "metric", "operator", "threshold", "for_seconds", "severity", "enabled"}:
            continue
        setattr(rule, k, v)
    await audit(db, request, admin, "alert_rule.update", rule.name, rule_id=rule.id)
    await db.commit()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    rule = await db.get(AlertRule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    await audit(db, request, admin, "alert_rule.delete", rule.name)
    await db.delete(rule)
    await db.commit()


def event_out(ev: AlertEvent, names: dict[str, str]) -> AlertEventOut:
    out = AlertEventOut.model_validate(ev)
    out.rule_name = ev.rule.name if ev.rule else None
    out.metric = ev.rule.metric if ev.rule else None
    out.agent_name = names.get(ev.agent_id or "")
    return out


@router.get("/events", response_model=list[AlertEventOut])
async def list_events(
    state: AlertState | None = None,
    agent_id: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    q = select(AlertEvent).order_by(AlertEvent.started_at.desc()).limit(limit)
    if state:
        q = q.where(AlertEvent.state == state)
    if agent_id:
        q = q.where(AlertEvent.agent_id == agent_id)
    events = (await db.execute(q)).scalars().all()
    names = dict((await db.execute(select(Agent.id, Agent.name))).all())
    return [event_out(e, names) for e in events]


@router.post("/events/{event_id}/ack", response_model=AlertEventOut)
async def ack_event(
    event_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_session),
):
    ev = await db.get(AlertEvent, event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    if ev.acknowledged_at is None:
        ev.acknowledged_by = user.id
        ev.acknowledged_at = datetime.now(timezone.utc)
        await audit(db, request, user, "alert.ack", ev.message[:255], event_id=ev.id)
        await db.commit()
    names = dict((await db.execute(select(Agent.id, Agent.name))).all())
    return event_out(ev, names)
