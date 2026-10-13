"""VPN management (Xray users, inbounds, nodes) and public subscriptions."""

from __future__ import annotations

import base64
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import audit, require_admin, require_operator, require_viewer
from ..models import Agent, User, VpnUser, VpnUserTrafficDaily, XrayInbound, XrayNodeState
from ..services import usage, xray
from ..services.ratelimit import SlidingWindowLimiter
from ..services.x25519 import generate_keypair
from ..vpn_schemas import SS_2022, InboundIn, InboundOut, InboundUpdate, VpnUserIn, VpnUserOut, VpnUserUpdate
from .agents import is_online

router = APIRouter(prefix="/vpn", tags=["vpn"])
public = APIRouter(tags=["subscription"])

GB = 1000**3  # decimal gigabytes, as providers bill traffic
ONLINE_WINDOW = timedelta(minutes=2)
sub_limiter = SlidingWindowLimiter(max_events=60, window_seconds=60)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _base_url(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    return f"{proto}://{host}"


def user_out(u: VpnUser, request: Request) -> VpnUserOut:
    now = _now()
    return VpnUserOut(
        id=u.id,
        username=u.username,
        status=u.status(now),
        data_limit=u.data_limit,
        used_up=u.used_up,
        used_down=u.used_down,
        used=u.used,
        lifetime_used=u.lifetime_used,
        expire_at=u.expire_at,
        enabled=u.enabled,
        inbound_ids=u.inbound_ids,
        note=u.note,
        created_at=u.created_at,
        last_online_at=u.last_online_at,
        online=bool(u.last_online_at and now - u.last_online_at < ONLINE_WINDOW),
        sub_token=u.sub_token,
        sub_url=f"{_base_url(request)}/sub/{u.sub_token}",
    )


async def _inbound_ids_valid(db: AsyncSession, ids: list[int] | None) -> None:
    if ids is None:
        return
    found = set((await db.execute(select(XrayInbound.id).where(XrayInbound.id.in_(ids)))).scalars())
    missing = set(ids) - found
    if missing:
        raise HTTPException(422, f"unknown inbound ids: {sorted(missing)}")


# ============================================================================ keys / helpers
@router.post("/tools/reality-keys")
async def reality_keys(_: User = Depends(require_admin)):
    priv, pub = generate_keypair()
    return {"private_key": priv, "public_key": pub, "short_id": secrets.token_hex(8)}


@router.post("/tools/ss2022-key")
async def ss2022_key(method: str = Query("2022-blake3-aes-128-gcm"), _: User = Depends(require_admin)):
    if method not in SS_2022:
        raise HTTPException(422, "not a 2022 method")
    return {"key": base64.b64encode(secrets.token_bytes(SS_2022[method])).decode()}


# ============================================================================ nodes
@router.get("/nodes")
async def nodes(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    agents = (await db.execute(select(Agent).order_by(Agent.name))).scalars().all()
    states = {s.agent_id: s for s in (await db.execute(select(XrayNodeState))).scalars()}
    counts = dict((await db.execute(select(XrayInbound.agent_id, func.count()).group_by(XrayInbound.agent_id))).all())
    inbounds = (await db.execute(select(XrayInbound))).scalars().all()
    users = (await db.execute(select(VpnUser))).scalars().all()
    out = []
    for a in agents:
        st = states.get(a.id)
        desired = xray.config_hash(xray.build_config([i for i in inbounds if i.agent_id == a.id], users))
        out.append(
            {
                "agent_id": a.id,
                "name": a.name,
                "online": is_online(a),
                "remote_addr": a.remote_addr,
                "xray_installed": bool((a.capabilities or {}).get("tools", {}).get("xray")),
                "xray_version": st.xray_version if st else None,
                "running": bool(st and st.running),
                "error": st.error if st else None,
                "in_sync": bool(st and st.applied_hash == desired),
                "applied_at": st.applied_at if st else None,
                "inbounds": counts.get(a.id, 0),
                "online_users": len(st.online_users or []) if st else 0,
            }
        )
    return out


# ============================================================================ inbounds
_LISTEN_STATES = {"LISTEN", "UNCONN"}


async def _port_in_use(db: AsyncSession, agent_id: str, port: int, network: str, exclude_inbound: int | None = None) -> bool:
    """True when the node's last inventory shows something else listening on the port
    (e.g. nginx on 443 on the panel server). Ports of our own inbounds don't count."""
    from ..models import AgentInventory

    own = (
        await db.execute(select(XrayInbound.id).where(XrayInbound.agent_id == agent_id, XrayInbound.port == port))
    ).scalars().all()
    if any(i != exclude_inbound for i in own):
        return False  # handled by the unique constraint
    if own:
        return False  # the listener is our own Xray inbound being edited
    inv = await db.get(AgentInventory, agent_id)
    for c in (inv.connections if inv else []) or []:
        if c.get("state") not in _LISTEN_STATES:
            continue
        if c.get("proto", "tcp").startswith("udp") and c.get("state") != "UNCONN":
            continue
        local = str(c.get("local", ""))
        if local.rsplit(":", 1)[-1] == str(port) and not local.startswith(("127.", "[::1]", "::1")):
            if c.get("proto", "tcp").startswith("tcp") or network == "tcp":
                return True
    return False


def _port_conflict(port: int) -> HTTPException:
    hint = " — it is the panel's HTTPS port; use e.g. 8443 or 2053" if port in (80, 443) else ""
    return HTTPException(409, f"Port {port} is already in use on this server{hint}")



def inbound_out(i: XrayInbound, names: dict[str, str], users: list[VpnUser], online: set[str] | None = None) -> InboundOut:
    out = InboundOut.model_validate(i)
    out.agent_name = names.get(i.agent_id)
    members = [u for u in users if xray.user_has_inbound(u, i)]
    out.users = len(members)
    if online:
        out.online = sum(1 for u in members if u.email in online)
    return out


@router.get("/inbounds", response_model=list[InboundOut])
async def list_inbounds(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(XrayInbound).order_by(XrayInbound.id))).scalars().all()
    names = dict((await db.execute(select(Agent.id, Agent.name))).all())
    users = (await db.execute(select(VpnUser))).scalars().all()
    online = {s.agent_id: set(s.online_users or []) for s in (await db.execute(select(XrayNodeState))).scalars()}
    return [inbound_out(i, names, users, online.get(i.agent_id)) for i in rows]


@router.post("/inbounds", response_model=InboundOut, status_code=201)
async def create_inbound(body: InboundIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    if await db.get(Agent, body.agent_id) is None:
        raise HTTPException(404, "Node not found")
    if await _port_in_use(db, body.agent_id, body.port, body.network):
        raise _port_conflict(body.port)
    row = XrayInbound(
        agent_id=body.agent_id,
        remark=body.remark,
        protocol=body.protocol,
        port=body.port,
        listen=body.listen,
        network=body.network,
        security=body.security,
        address=body.address,
        settings=body.settings.model_dump(),
        enabled=body.enabled,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(409, f"Port {body.port} is already used by another inbound on this node") from e
    await audit(db, request, admin, "vpn.inbound.create", body.remark, inbound_id=row.id, port=body.port, protocol=body.protocol)
    await db.commit()
    names = dict((await db.execute(select(Agent.id, Agent.name))).all())
    return inbound_out(row, names, [])


@router.put("/inbounds/{inbound_id}", response_model=InboundOut)
async def update_inbound(inbound_id: int, body: InboundUpdate, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await db.get(XrayInbound, inbound_id)
    if row is None:
        raise HTTPException(404, "Inbound not found")
    if body.agent_id and body.agent_id != row.agent_id:
        if await db.get(Agent, body.agent_id) is None:
            raise HTTPException(404, "Node not found")
        row.agent_id = body.agent_id
    if (body.port != row.port or body.agent_id) and await _port_in_use(db, row.agent_id, body.port, body.network, exclude_inbound=row.id):
        raise _port_conflict(body.port)
    for f in ("remark", "protocol", "port", "listen", "network", "security", "address", "enabled"):
        setattr(row, f, getattr(body, f))
    row.settings = body.settings.model_dump()
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(409, f"Port {body.port} is already used by another inbound on this node") from e
    await audit(db, request, admin, "vpn.inbound.update", row.remark, inbound_id=row.id)
    await db.commit()
    names = dict((await db.execute(select(Agent.id, Agent.name))).all())
    users = (await db.execute(select(VpnUser))).scalars().all()
    return inbound_out(row, names, users)


@router.delete("/inbounds/{inbound_id}", status_code=204)
async def delete_inbound(inbound_id: int, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await db.get(XrayInbound, inbound_id)
    if row is None:
        raise HTTPException(404, "Inbound not found")
    # Drop the id from users that were restricted to specific inbounds.
    for u in (await db.execute(select(VpnUser).where(VpnUser.inbound_ids.is_not(None)))).scalars():
        if inbound_id in (u.inbound_ids or []):
            u.inbound_ids = [i for i in u.inbound_ids if i != inbound_id]
    await audit(db, request, admin, "vpn.inbound.delete", row.remark, inbound_id=row.id)
    await db.delete(row)
    await db.commit()


# ============================================================================ users
def _apply_expiry(u: VpnUser, expire_at: datetime | None, expire_days: int | None) -> None:
    if expire_days:
        u.expire_at = _now() + timedelta(days=expire_days)
    elif expire_at is not None:
        u.expire_at = expire_at if expire_at.tzinfo else expire_at.replace(tzinfo=timezone.utc)


@router.get("/users", response_model=list[VpnUserOut])
async def list_users(
    request: Request,
    search: str | None = None,
    status: str | None = None,
    _: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_session),
):
    q = select(VpnUser).order_by(VpnUser.id.desc())
    if search:
        q = q.where(VpnUser.username.ilike(f"%{search.replace('%', '')}%"))
    rows = [user_out(u, request) for u in (await db.execute(q)).scalars()]
    if status:
        rows = [r for r in rows if r.status == status or (status == "online" and r.online)]
    return rows


@router.post("/users", response_model=VpnUserOut, status_code=201)
async def create_user(body: VpnUserIn, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    await _inbound_ids_valid(db, body.inbound_ids)
    u = VpnUser(
        username=body.username,
        password=secrets.token_urlsafe(18),
        sub_token=secrets.token_urlsafe(24),
        data_limit=int(body.data_limit_gb * GB),
        enabled=body.enabled,
        inbound_ids=body.inbound_ids,
        note=body.note,
    )
    _apply_expiry(u, body.expire_at, body.expire_days)
    db.add(u)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(409, "A user with this name already exists") from e
    await audit(db, request, op, "vpn.user.create", u.username, user_id=u.id)
    await db.commit()
    return user_out(u, request)


async def _get_user(db: AsyncSession, user_id: int) -> VpnUser:
    u = await db.get(VpnUser, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    return u


@router.get("/users/{user_id}", response_model=VpnUserOut)
async def get_user(user_id: int, request: Request, _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    return user_out(await _get_user(db, user_id), request)


@router.patch("/users/{user_id}", response_model=VpnUserOut)
async def update_user(user_id: int, body: VpnUserUpdate, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    u = await _get_user(db, user_id)
    if body.username is not None:
        u.username = body.username
    if body.data_limit_gb is not None:
        u.data_limit = int(body.data_limit_gb * GB)
    if body.clear_expire:
        u.expire_at = None
    else:
        _apply_expiry(u, body.expire_at, body.expire_days)
    if body.enabled is not None:
        u.enabled = body.enabled
    if body.all_inbounds:
        u.inbound_ids = None
    elif body.inbound_ids is not None:
        await _inbound_ids_valid(db, body.inbound_ids)
        u.inbound_ids = body.inbound_ids
    if body.note is not None:
        u.note = body.note
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(409, "A user with this name already exists") from e
    await audit(db, request, op, "vpn.user.update", u.username, user_id=u.id)
    await db.commit()
    return user_out(u, request)


@router.post("/users/{user_id}/reset-traffic", response_model=VpnUserOut)
async def reset_traffic(user_id: int, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    u = await _get_user(db, user_id)
    u.used_up = 0
    u.used_down = 0
    u.traffic_reset_at = _now()
    await audit(db, request, op, "vpn.user.reset_traffic", u.username, user_id=u.id)
    await db.commit()
    return user_out(u, request)


@router.post("/users/{user_id}/revoke", response_model=VpnUserOut)
async def revoke(user_id: int, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    """New UUID, password and subscription link: every old config stops working."""
    import uuid as _uuid

    u = await _get_user(db, user_id)
    u.uuid = str(_uuid.uuid4())
    u.password = secrets.token_urlsafe(18)
    u.sub_token = secrets.token_urlsafe(24)
    await audit(db, request, op, "vpn.user.revoke", u.username, user_id=u.id)
    await db.commit()
    return user_out(u, request)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: int, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    u = await _get_user(db, user_id)
    await audit(db, request, op, "vpn.user.delete", u.username, user_id=u.id)
    await db.delete(u)
    await db.commit()


@router.get("/users/{user_id}/links")
async def user_links(user_id: int, _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    u = await _get_user(db, user_id)
    inbounds = (await db.execute(select(XrayInbound))).scalars().all()
    return {"links": xray.user_links(u, inbounds)}


@router.get("/users/{user_id}/usage")
async def user_usage(user_id: int, days: int = Query(30, ge=1, le=365), _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    await _get_user(db, user_id)
    since = usage.days_back(usage.today(), days - 1)
    rows = (
        await db.execute(
            select(VpnUserTrafficDaily).where(VpnUserTrafficDaily.user_id == user_id, VpnUserTrafficDaily.day >= since).order_by(VpnUserTrafficDaily.day)
        )
    ).scalars().all()
    return [{"day": r.day, "up": r.up, "down": r.down} for r in rows]


# ============================================================================ overview
@router.get("/overview")
async def overview(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    now = _now()
    users = (await db.execute(select(VpnUser))).scalars().all()
    by_status: dict[str, int] = {"active": 0, "expired": 0, "limited": 0, "disabled": 0}
    for u in users:
        by_status[u.status(now)] += 1
    online = sum(1 for u in users if u.last_online_at and now - u.last_online_at < ONLINE_WINDOW)
    t = usage.today()
    m = usage.month_start(t)
    since = usage.days_back(t, 29)
    daily = (
        await db.execute(
            select(VpnUserTrafficDaily.day, func.sum(VpnUserTrafficDaily.up), func.sum(VpnUserTrafficDaily.down))
            .where(VpnUserTrafficDaily.day >= min(since, m))
            .group_by(VpnUserTrafficDaily.day)
            .order_by(VpnUserTrafficDaily.day)
        )
    ).all()
    today_up = sum(int(u or 0) for d, u, _ in daily if d == t)
    today_down = sum(int(dn or 0) for d, _, dn in daily if d == t)
    month_up = sum(int(u or 0) for d, u, _ in daily if d >= m)
    month_down = sum(int(dn or 0) for d, _, dn in daily if d >= m)
    top = sorted(users, key=lambda u: -u.used)[:8]
    soon = sorted(
        [u for u in users if u.status(now) == "active" and u.expire_at and u.expire_at - now < timedelta(days=3)],
        key=lambda u: u.expire_at,
    )[:8]
    inbounds = (await db.execute(select(func.count()).select_from(XrayInbound))).scalar_one()
    return {
        "users_total": len(users),
        "users_by_status": by_status,
        "users_online": online,
        "inbounds": inbounds,
        "traffic": {"today_up": today_up, "today_down": today_down, "month_up": month_up, "month_down": month_down},
        "daily": [{"day": d, "up": int(u or 0), "down": int(dn or 0)} for d, u, dn in daily if d >= since],
        "top_users": [{"id": u.id, "username": u.username, "used": u.used, "data_limit": u.data_limit} for u in top],
        "expiring_soon": [{"id": u.id, "username": u.username, "expire_at": u.expire_at} for u in soon],
        "timezone": str(usage.usage_tz()),
    }


# ============================================================================ public subscription
async def _sub_user(db: AsyncSession, token: str, request: Request) -> VpnUser:
    from ..deps import client_ip

    if not sub_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many requests")
    if len(token) > 64:
        raise HTTPException(404, "Not found")
    u = (await db.execute(select(VpnUser).where(VpnUser.sub_token == token))).scalar_one_or_none()
    if u is None:
        raise HTTPException(404, "Not found")
    return u


def _userinfo_header(u: VpnUser) -> str:
    expire = int(u.expire_at.timestamp()) if u.expire_at else 0
    return f"upload={u.used_up}; download={u.used_down}; total={u.data_limit}; expire={expire}"


_BROWSERS = ("mozilla", "chrome", "safari", "edg/", "opera")
_CLIENT_HINTS = ("v2ray", "clash", "mihomo", "stash", "sing-box", "hiddify", "streisand", "shadowrocket", "nekobox", "nekoray", "foxray", "karing", "happ", "v2box", "quantumult", "surge", "loon")


@public.get("/sub/{token}")
async def subscription(
    token: str,
    request: Request,
    format: str | None = Query(None, pattern="^(base64|links|clash)$"),
    db: AsyncSession = Depends(get_session),
):
    u = await _sub_user(db, token, request)
    ua = request.headers.get("user-agent", "").lower()
    accept = request.headers.get("accept", "")
    if format is None and "text/html" in accept and any(b in ua for b in _BROWSERS) and not any(c in ua for c in _CLIENT_HINTS):
        return RedirectResponse(f"/s/{token}", status_code=302)
    inbounds = (await db.execute(select(XrayInbound))).scalars().all()
    active = u.status() == "active"
    fmt = format or ("clash" if any(c in ua for c in ("clash", "mihomo", "stash")) else "base64")
    headers = {
        "subscription-userinfo": _userinfo_header(u),
        "profile-update-interval": "12",
        "profile-title": "base64:" + base64.b64encode(f"Unknown Monitor · {u.username}".encode()).decode(),
        "content-disposition": f'attachment; filename="{u.username}"',
        "cache-control": "no-store",
    }
    if fmt == "clash":
        body = xray.clash_config(u, inbounds) if active else "proxies: []\n"
        return Response(body, media_type="text/yaml; charset=utf-8", headers=headers)
    links = "\n".join(xray.user_links(u, inbounds)) if active else ""
    if fmt == "links":
        return PlainTextResponse(links, headers=headers)
    return PlainTextResponse(base64.b64encode(links.encode()).decode(), headers=headers)


@public.get("/api/sub/{token}/info")
async def subscription_info(token: str, request: Request, db: AsyncSession = Depends(get_session)):
    u = await _sub_user(db, token, request)
    inbounds = (await db.execute(select(XrayInbound))).scalars().all()
    status = u.status()
    return {
        "username": u.username,
        "status": status,
        "used_up": u.used_up,
        "used_down": u.used_down,
        "used": u.used,
        "data_limit": u.data_limit,
        "expire_at": u.expire_at,
        "online": bool(u.last_online_at and _now() - u.last_online_at < ONLINE_WINDOW),
        "sub_url": f"{_base_url(request)}/sub/{u.sub_token}",
        "links": xray.user_links(u, inbounds) if status == "active" else [],
    }
