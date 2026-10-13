from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import audit, require_admin, require_viewer
from ..models import Agent, AgentInventory, EnrollmentToken, InterfaceSample, MetricSample, User
from ..schemas import AgentOut, AgentUpdate, EnrollmentTokenCreate, EnrollmentTokenOut
from ..security import hash_token, random_token
from ..services.timeseries import bucket_expr, pick_bucket, resolve_range

router = APIRouter(tags=["agents"])

LATEST_FIELDS = (
    "ts",
    "cpu_percent",
    "mem_percent",
    "disk_percent",
    "load1",
    "rx_bps",
    "tx_bps",
    "tcp_established",
    "uptime_seconds",
)


def is_online(agent: Agent, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return (
        agent.last_seen_at is not None
        and not agent.disabled
        and (now - agent.last_seen_at).total_seconds() <= get_settings().agent_offline_seconds
    )


async def latest_metrics(db: AsyncSession, agent_ids: list[str] | None = None) -> dict[str, dict]:
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    newest = select(MetricSample.agent_id, func.max(MetricSample.ts).label("ts")).where(
        MetricSample.ts >= since
    )
    if agent_ids is not None:
        newest = newest.where(MetricSample.agent_id.in_(agent_ids))
    newest = newest.group_by(MetricSample.agent_id).subquery()
    q = select(MetricSample).join(
        newest, (MetricSample.agent_id == newest.c.agent_id) & (MetricSample.ts == newest.c.ts)
    )
    rows = (await db.execute(q)).scalars().all()
    return {r.agent_id: {f: getattr(r, f) for f in LATEST_FIELDS} for r in rows}


def agent_out(agent: Agent, latest: dict | None) -> AgentOut:
    out = AgentOut.model_validate(agent)
    out.online = is_online(agent)
    out.latest = latest
    return out


async def get_agent_or_404(db: AsyncSession, agent_id: str) -> Agent:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "Agent not found")
    return agent


@router.get("/agents", response_model=list[AgentOut])
async def list_agents(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    agents = (await db.execute(select(Agent).order_by(Agent.name))).scalars().all()
    latest = await latest_metrics(db)
    return [agent_out(a, latest.get(a.id)) for a in agents]


@router.get("/agents/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: str, _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)
):
    agent = await get_agent_or_404(db, agent_id)
    latest = await latest_metrics(db, [agent.id])
    return agent_out(agent, latest.get(agent.id))


@router.patch("/agents/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    agent = await get_agent_or_404(db, agent_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(agent, k, v)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(409, "Agent name already in use") from e
    await audit(db, request, admin, "agent.update", agent.name, **changes)
    await db.commit()
    return agent_out(agent, None)


@router.post("/agents/{agent_id}/rotate-token", response_model=dict)
async def rotate_agent_token(
    agent_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    """Issue a new agent credential. The old one stops working immediately; the
    new value must be written to /etc/ipf3/agent.json on the host."""
    agent = await get_agent_or_404(db, agent_id)
    secret = random_token(32)
    agent.token_hash = hash_token(secret)
    await audit(db, request, admin, "agent.rotate_token", agent.name)
    await db.commit()
    return {"agent_id": agent.id, "agent_token": f"{agent.id}.{secret}"}


@router.delete("/agents/{agent_id}", status_code=204)
async def delete_agent(
    agent_id: str,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    agent = await get_agent_or_404(db, agent_id)
    await audit(db, request, admin, "agent.delete", agent.name, agent_id=agent.id)
    await db.delete(agent)
    await db.commit()


# --------------------------------------------------------------------------- telemetry
@router.get("/agents/{agent_id}/metrics")
async def agent_metrics(
    agent_id: str,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    bucket: int | None = Query(None, ge=10, le=86400),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    await get_agent_or_404(db, agent_id)
    start, end = resolve_range(start, end)
    b = pick_bucket(start, end, bucket)
    t = bucket_expr(MetricSample.ts, b).label("t")
    cols = [
        "cpu_percent",
        "mem_percent",
        "swap_percent",
        "disk_percent",
        "load1",
        "load5",
        "load15",
        "rx_bps",
        "tx_bps",
        "tcp_established",
        "tcp_time_wait",
        "udp_sockets",
    ]
    q = (
        select(
            t,
            *[func.avg(getattr(MetricSample, c)).label(c) for c in cols],
            func.max(MetricSample.rx_bps).label("rx_bps_max"),
            func.max(MetricSample.tx_bps).label("tx_bps_max"),
            (func.max(MetricSample.tcp_retrans_segs) - func.min(MetricSample.tcp_retrans_segs)).label(
                "tcp_retrans"
            ),
        )
        .where(MetricSample.agent_id == agent_id, MetricSample.ts >= start, MetricSample.ts < end)
        .group_by(t)
        .order_by(t)
    )
    rows = (await db.execute(q)).mappings().all()
    return {"bucket": b, "from": start, "to": end, "points": [dict(r) for r in rows]}


@router.get("/agents/{agent_id}/interfaces/metrics")
async def interface_metrics(
    agent_id: str,
    iface: str | None = None,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    bucket: int | None = Query(None, ge=10, le=86400),
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    await get_agent_or_404(db, agent_id)
    start, end = resolve_range(start, end)
    b = pick_bucket(start, end, bucket)
    t = bucket_expr(InterfaceSample.ts, b).label("t")
    q = (
        select(
            t,
            InterfaceSample.iface,
            func.avg(InterfaceSample.rx_bps).label("rx_bps"),
            func.avg(InterfaceSample.tx_bps).label("tx_bps"),
            func.max(InterfaceSample.rx_bps).label("rx_bps_max"),
            func.max(InterfaceSample.tx_bps).label("tx_bps_max"),
            func.avg(InterfaceSample.rx_pps).label("rx_pps"),
            func.avg(InterfaceSample.tx_pps).label("tx_pps"),
            func.sum(InterfaceSample.rx_errs + InterfaceSample.tx_errs).label("errors"),
            func.sum(InterfaceSample.rx_drops + InterfaceSample.tx_drops).label("drops"),
        )
        .where(InterfaceSample.agent_id == agent_id, InterfaceSample.ts >= start, InterfaceSample.ts < end)
        .group_by(t, InterfaceSample.iface)
        .order_by(t)
    )
    if iface:
        q = q.where(InterfaceSample.iface == iface)
    rows = (await db.execute(q)).mappings().all()
    return {"bucket": b, "from": start, "to": end, "points": [dict(r) for r in rows]}


@router.get("/agents/{agent_id}/inventory")
async def agent_inventory(
    agent_id: str, _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)
):
    await get_agent_or_404(db, agent_id)
    inv = await db.get(AgentInventory, agent_id)
    if inv is None:
        return {
            "updated_at": None,
            "interfaces": [],
            "routes": [],
            "routes6": [],
            "connections": [],
            "dns": {},
            "system": {},
        }
    return {
        "updated_at": inv.updated_at,
        "interfaces": inv.interfaces,
        "routes": inv.routes,
        "routes6": inv.routes6,
        "connections": inv.connections,
        "dns": inv.dns,
        "system": inv.system,
    }


# --------------------------------------------------------------------------- enrollment
@router.get("/enrollment-tokens", response_model=list[EnrollmentTokenOut])
async def list_enrollment_tokens(
    _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)
):
    q = select(EnrollmentToken).order_by(EnrollmentToken.created_at.desc()).limit(200)
    return (await db.execute(q)).scalars().all()


@router.post("/enrollment-tokens", response_model=EnrollmentTokenOut, status_code=201)
async def create_enrollment_token(
    body: EnrollmentTokenCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    ttl = body.ttl_hours or get_settings().enrollment_token_ttl_hours
    token = "ipf3e_" + random_token(32)
    row = EnrollmentToken(
        token_hash=hash_token(token),
        note=body.note,
        created_by=admin.id,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl),
    )
    db.add(row)
    await db.flush()
    await audit(db, request, admin, "enrollment_token.create", body.note, token_id=row.id, ttl_hours=ttl)
    await db.commit()
    out = EnrollmentTokenOut.model_validate(row)
    out.token = token  # shown exactly once
    return out


@router.delete("/enrollment-tokens/{token_id}", status_code=204)
async def delete_enrollment_token(
    token_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    row = await db.get(EnrollmentToken, token_id)
    if row is None:
        raise HTTPException(404, "Token not found")
    await audit(db, request, admin, "enrollment_token.delete", row.note, token_id=row.id)
    await db.delete(row)
    await db.commit()
