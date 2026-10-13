"""Who is using a VPN account: client apps (from subscription fetches) and the IPs
currently connected (from each node's Xray online IP list)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Agent, VpnUser, VpnUserApp, XrayNodeState

MAX_APPS_PER_USER = 20
STATE_FRESH = timedelta(minutes=2)

# (needle in the lower-cased User-Agent, display name); first match wins.
_APPS = (
    ("v2rayng", "v2rayNG"),
    ("v2rayn", "v2rayN"),
    ("v2raytun", "v2RayTun"),
    ("hiddify", "Hiddify"),
    ("streisand", "Streisand"),
    ("v2box", "V2Box"),
    ("foxray", "FoXray"),
    ("shadowrocket", "Shadowrocket"),
    ("happ", "Happ"),
    ("nekobox", "NekoBox"),
    ("nekoray", "NekoRay"),
    ("throne", "Throne"),
    ("karing", "Karing"),
    ("incy", "INCY"),
    ("stash", "Stash"),
    ("clash-verge", "Clash Verge"),
    ("clashmeta", "Clash Meta"),
    ("clash.meta", "Clash Meta"),
    ("mihomo", "mihomo"),
    ("flclash", "FlClash"),
    ("clash", "Clash"),
    ("sing-box", "sing-box"),
    ("sfa", "sing-box"),
    ("sfi", "sing-box"),
    ("quantumult", "Quantumult X"),
    ("surge", "Surge"),
    ("loon", "Loon"),
    ("okhttp", "Android app"),
    ("cfnetwork", "iOS app"),
    ("go-http-client", "Go client"),
    ("curl", "curl"),
    ("wget", "wget"),
)
_VERSION = re.compile(r"(\d+(?:\.\d+){0,3})")


def parse_user_agent(ua: str) -> tuple[str, str]:
    """User-Agent → (app name, version)."""
    low = ua.lower()
    for needle, name in _APPS:
        i = low.find(needle)
        if i >= 0:
            m = _VERSION.search(ua[i + len(needle): i + len(needle) + 24])
            return name, (m.group(1) if m else "")
    if not ua.strip():
        return "Unknown app", ""
    head = ua.split()[0]
    name, _, ver = head.partition("/")
    m = _VERSION.match(ver)
    return (name[:64] or "Unknown app"), (m.group(1) if m else "")


async def record_fetch(db: AsyncSession, user: VpnUser, ua: str, ip: str, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    ua = (ua or "").strip()[:256]
    app, version = parse_user_agent(ua)
    stmt = pg_insert(VpnUserApp).values(
        user_id=user.id, user_agent=ua, app=app[:64], version=version[:32], last_ip=ip[:64], first_at=now, last_at=now, fetches=1
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_vpn_user_apps_user_ua",
        set_={"last_ip": stmt.excluded.last_ip, "last_at": now, "fetches": VpnUserApp.fetches + 1, "app": stmt.excluded.app, "version": stmt.excluded.version},
    )
    await db.execute(stmt)
    keep = select(VpnUserApp.id).where(VpnUserApp.user_id == user.id).order_by(VpnUserApp.last_at.desc()).limit(MAX_APPS_PER_USER)
    await db.execute(delete(VpnUserApp).where(VpnUserApp.user_id == user.id, VpnUserApp.id.not_in(keep.scalar_subquery())))


async def user_apps(db: AsyncSession, user_id: int) -> list[dict[str, Any]]:
    rows = (await db.execute(select(VpnUserApp).where(VpnUserApp.user_id == user_id).order_by(VpnUserApp.last_at.desc()))).scalars()
    return [
        {"app": r.app, "version": r.version, "user_agent": r.user_agent, "last_ip": r.last_ip, "first_at": r.first_at, "last_at": r.last_at, "fetches": r.fetches}
        for r in rows
    ]


async def user_connections(db: AsyncSession, user_id: int, now: datetime | None = None) -> list[dict[str, Any]]:
    """IPs connected right now, per node (from states reported in the last 2 min)."""
    now = now or datetime.now(timezone.utc)
    email = f"u{user_id}"
    rows = (await db.execute(select(XrayNodeState, Agent.name).join(Agent, Agent.id == XrayNodeState.agent_id))).all()
    out = []
    for st, node in rows:
        if not st.updated_at or now - st.updated_at > STATE_FRESH:
            continue
        for ip, ts in ((st.online_ips or {}).get(email) or {}).items():
            out.append({"ip": ip, "node": node, "last_seen": datetime.fromtimestamp(ts, timezone.utc) if ts else st.updated_at})
    out.sort(key=lambda c: c["last_seen"], reverse=True)
    return out


async def online_ip_counts(db: AsyncSession, now: datetime | None = None) -> dict[int, int]:
    """Distinct connected IPs per user id, across all nodes."""
    now = now or datetime.now(timezone.utc)
    ips: dict[int, set[str]] = {}
    for st in (await db.execute(select(XrayNodeState))).scalars():
        if not st.updated_at or now - st.updated_at > STATE_FRESH:
            continue
        for email, m in (st.online_ips or {}).items():
            if email.startswith("u") and email[1:].isdigit():
                ips.setdefault(int(email[1:]), set()).update(m)
    return {k: len(v) for k, v in ips.items()}
