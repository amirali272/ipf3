"""VPN outbounds (upstream proxies) and routing rules."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import audit, require_admin, require_viewer
from ..models import Agent, User, XrayOutbound, XrayRoutingRule
from ..services import outbound as ob
from ..services.xray import rule_config
from ..vpn_schemas import OutboundDetail, OutboundIn, OutboundOut, RuleIn, RuleOrderIn, RuleOut

router = APIRouter(prefix="/vpn", tags=["vpn"])


async def _validate(config: dict) -> None:
    s = get_settings()
    err = await asyncio.to_thread(ob.xray_test, config, s.xray_bin, s.xray_assets)
    if err:
        raise HTTPException(422, f"Xray rejected this configuration: {err}")


def _outbound_out(o: XrayOutbound, names: dict[str, str], rule_counts: dict[int, int], detail: bool = False) -> OutboundOut:
    info = ob.summary(o.config)
    nodes = list(names.values()) if o.agent_ids is None else [names[a] for a in o.agent_ids if a in names]
    data = dict(
        id=o.id, remark=o.remark, protocol=o.protocol, address=info["address"], port=info["port"], network=info["network"],
        security=info["security"], agent_ids=o.agent_ids, nodes=nodes, enabled=o.enabled, up=o.up, down=o.down,
        rules=rule_counts.get(o.id, 0), created_at=o.created_at,
    )
    if detail:
        return OutboundDetail(**data, link=o.link, config=o.config)
    return OutboundOut(**data)


async def _context(db: AsyncSession) -> tuple[dict[str, str], dict[int, int]]:
    names = dict((await db.execute(select(Agent.id, Agent.name).order_by(Agent.name))).all())
    counts = dict(
        (await db.execute(select(XrayRoutingRule.outbound_id, func.count()).where(XrayRoutingRule.outbound_id.is_not(None)).group_by(XrayRoutingRule.outbound_id))).all()
    )
    return names, counts


async def _apply_body(body: OutboundIn, row: XrayOutbound, db: AsyncSession) -> None:
    if body.link.strip():
        try:
            config, name = ob.parse_link(body.link)
        except ob.LinkError as e:
            raise HTTPException(422, str(e)) from None
        row.link = body.link.strip()
    else:
        try:
            config, name = ob.from_json(body.config or {}), ""
        except ob.LinkError as e:
            raise HTTPException(422, str(e)) from None
        row.link = ""
    if body.agent_ids is not None:
        known = set((await db.execute(select(Agent.id).where(Agent.id.in_(body.agent_ids)))).scalars())
        if missing := set(body.agent_ids) - known:
            raise HTTPException(404, f"Unknown node: {sorted(missing)[0]}")
    await _validate({"log": {"loglevel": "none"}, "outbounds": [{**config, "tag": "candidate"}]})
    row.config = config
    row.protocol = config["protocol"]
    row.remark = body.remark.strip() or name[:128] or f"{config['protocol']} outbound"
    row.agent_ids = body.agent_ids
    row.enabled = body.enabled


# ============================================================================ outbounds
@router.get("/outbounds", response_model=list[OutboundOut])
async def list_outbounds(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(XrayOutbound).order_by(XrayOutbound.id))).scalars().all()
    names, counts = await _context(db)
    return [_outbound_out(o, names, counts) for o in rows]


@router.post("/outbounds/parse")
async def parse_outbound(body: OutboundIn, _: User = Depends(require_admin)):
    """Preview what a link turns into, without saving it."""
    try:
        config, name = ob.parse_link(body.link) if body.link.strip() else (ob.from_json(body.config or {}), "")
    except ob.LinkError as e:
        raise HTTPException(422, str(e)) from None
    return {"remark": name, "config": config, **ob.summary(config)}


@router.get("/outbounds/{outbound_id}", response_model=OutboundDetail)
async def get_outbound(outbound_id: int, _: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await db.get(XrayOutbound, outbound_id)
    if row is None:
        raise HTTPException(404, "Outbound not found")
    names, counts = await _context(db)
    return _outbound_out(row, names, counts, detail=True)


@router.post("/outbounds", response_model=OutboundOut, status_code=201)
async def create_outbound(body: OutboundIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = XrayOutbound(up=0, down=0)
    await _apply_body(body, row, db)
    db.add(row)
    await db.flush()
    await audit(db, request, admin, "vpn.outbound.create", row.remark, outbound_id=row.id, protocol=row.protocol)
    await db.commit()
    names, counts = await _context(db)
    return _outbound_out(row, names, counts)


@router.put("/outbounds/{outbound_id}", response_model=OutboundOut)
async def update_outbound(outbound_id: int, body: OutboundIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await db.get(XrayOutbound, outbound_id)
    if row is None:
        raise HTTPException(404, "Outbound not found")
    await _apply_body(body, row, db)
    await audit(db, request, admin, "vpn.outbound.update", row.remark, outbound_id=row.id)
    await db.commit()
    names, counts = await _context(db)
    return _outbound_out(row, names, counts)


@router.delete("/outbounds/{outbound_id}", status_code=204)
async def delete_outbound(outbound_id: int, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await db.get(XrayOutbound, outbound_id)
    if row is None:
        raise HTTPException(404, "Outbound not found")
    used = (await db.execute(select(func.count()).select_from(XrayRoutingRule).where(XrayRoutingRule.outbound_id == outbound_id))).scalar_one()
    if used:
        raise HTTPException(409, f"{used} routing rule(s) use this outbound — delete or change them first")
    await audit(db, request, admin, "vpn.outbound.delete", row.remark, outbound_id=row.id)
    await db.delete(row)
    await db.commit()


# ============================================================================ routing rules
def _rule_out(r: XrayRoutingRule, outbounds: dict[int, str]) -> RuleOut:
    return RuleOut.model_construct(
        id=r.id, position=r.position, remark=r.remark, action=r.action, outbound_id=r.outbound_id,
        outbound=outbounds.get(r.outbound_id) if r.outbound_id else None, inbound_ids=r.inbound_ids or [], user_ids=r.user_ids or [],
        domains=r.domains or [], ips=r.ips or [], port=r.port, network=r.network, protocols=r.protocols or [], enabled=r.enabled,
    )


async def _outbound_names(db: AsyncSession) -> dict[int, str]:
    return dict((await db.execute(select(XrayOutbound.id, XrayOutbound.remark))).all())


async def _check_rule(body: RuleIn, db: AsyncSession) -> None:
    if body.outbound_id is not None and await db.get(XrayOutbound, body.outbound_id) is None:
        raise HTTPException(404, "Outbound not found")
    probe = XrayRoutingRule(**body.model_dump(exclude={"outbound_id"}), outbound_id=body.outbound_id)
    r = rule_config(probe, {f"in-{i}" for i in body.inbound_ids}, {f"out-{body.outbound_id}"})
    if r is None:
        return
    r["outboundTag"] = "direct"
    r.pop("inboundTag", None)
    await _validate({"log": {"loglevel": "none"}, "outbounds": [{"tag": "direct", "protocol": "freedom"}], "routing": {"rules": [r]}})


def _apply_rule(row: XrayRoutingRule, body: RuleIn) -> None:
    for k, v in body.model_dump().items():
        setattr(row, k, v)


@router.get("/routing", response_model=list[RuleOut])
async def list_rules(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(XrayRoutingRule).order_by(XrayRoutingRule.position, XrayRoutingRule.id))).scalars().all()
    names = await _outbound_names(db)
    return [_rule_out(r, names) for r in rows]


@router.post("/routing", response_model=RuleOut, status_code=201)
async def create_rule(body: RuleIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    await _check_rule(body, db)
    top = (await db.execute(select(func.max(XrayRoutingRule.position)))).scalar_one()
    row = XrayRoutingRule(position=(top or 0) + 1)
    _apply_rule(row, body)
    db.add(row)
    await db.flush()
    await audit(db, request, admin, "vpn.routing.create", row.remark, rule_id=row.id, rule_action=row.action)
    await db.commit()
    return _rule_out(row, await _outbound_names(db))


@router.put("/routing/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, body: RuleIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await db.get(XrayRoutingRule, rule_id)
    if row is None:
        raise HTTPException(404, "Rule not found")
    await _check_rule(body, db)
    _apply_rule(row, body)
    await audit(db, request, admin, "vpn.routing.update", row.remark, rule_id=row.id)
    await db.commit()
    return _rule_out(row, await _outbound_names(db))


@router.delete("/routing/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await db.get(XrayRoutingRule, rule_id)
    if row is None:
        raise HTTPException(404, "Rule not found")
    await audit(db, request, admin, "vpn.routing.delete", row.remark, rule_id=row.id)
    await db.delete(row)
    await db.commit()


@router.post("/routing/order", response_model=list[RuleOut])
async def reorder_rules(body: RuleOrderIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    rows = {r.id: r for r in (await db.execute(select(XrayRoutingRule))).scalars()}
    if sorted(body.ids) != sorted(rows):
        raise HTTPException(422, "ids must list every rule exactly once")
    for pos, rid in enumerate(body.ids, start=1):
        rows[rid].position = pos
    await audit(db, request, admin, "vpn.routing.reorder", "", ids=body.ids)
    await db.commit()
    names = await _outbound_names(db)
    return [_rule_out(rows[i], names) for i in body.ids]
