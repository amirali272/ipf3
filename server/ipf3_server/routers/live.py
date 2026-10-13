"""WebSocket feed of the latest real samples for the dashboard.

Each connection polls the database (cheap indexed queries) so the feed works
unchanged with several uvicorn workers behind the reverse proxy."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from ..config import get_settings
from ..db import sessionmaker
from ..models import Agent, AlertEvent, AlertState, InterfaceSample, LiveRate, MetricSample, User
from ..security import SESSION_COOKIE, decode_session_token
from .agents import is_online

router = APIRouter()

POLL_SECONDS = 2.0


def _json_default(o):
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError


async def _authenticate(ws: WebSocket) -> User | None:
    s = get_settings()
    origin = ws.headers.get("origin")
    host = ws.headers.get("host")
    # Cookies are sent on cross-site WebSocket handshakes; enforce same origin.
    if origin:
        allowed = {f"https://{host}", f"http://{host}", *s.cors_origins}
        if origin not in allowed:
            return None
    token = ws.cookies.get(SESSION_COOKIE)
    payload = decode_session_token(token) if token else None
    if payload is None:
        return None
    async with sessionmaker()() as db:
        user = await db.get(User, int(payload["sub"]))
        if user is None or not user.is_active or user.session_version != payload["sv"]:
            return None
        return user


@router.websocket("/ws/live")
async def live(ws: WebSocket):
    user = await _authenticate(ws)
    if user is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    focus_agent: str | None = None
    last_metric_id = 0
    last_iface_id = 0

    async def receiver():
        nonlocal focus_agent
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and "focus" in data:
                f = data["focus"]
                focus_agent = f if isinstance(f, str) and len(f) <= 36 else None

    recv_task = asyncio.create_task(receiver())
    try:
        current_focus: str | None = None
        while True:
            if recv_task.done():
                break
            if focus_agent != current_focus:
                current_focus = focus_agent
                last_iface_id = 0
            # Cursors start at 0: seed with the last 30 s only.
            since = datetime.now(timezone.utc) - timedelta(seconds=30)
            async with sessionmaker()() as db:
                mq = select(MetricSample).where(MetricSample.id > last_metric_id).order_by(MetricSample.id).limit(1000)
                if last_metric_id == 0:
                    mq = mq.where(MetricSample.ts >= since)
                metrics = (await db.execute(mq)).scalars().all()
                if metrics:
                    last_metric_id = metrics[-1].id
                ifaces = []
                if current_focus:
                    iq = (
                        select(InterfaceSample)
                        .where(InterfaceSample.agent_id == current_focus, InterfaceSample.id > last_iface_id)
                        .order_by(InterfaceSample.id)
                        .limit(2000)
                    )
                    if last_iface_id == 0:
                        iq = iq.where(InterfaceSample.ts >= since)
                    ifaces = (await db.execute(iq)).scalars().all()
                    if ifaces:
                        last_iface_id = ifaces[-1].id
                agents = (await db.execute(select(Agent))).scalars().all()
                live_rows = (
                    await db.execute(
                        select(LiveRate).where(LiveRate.ts >= datetime.now(timezone.utc) - timedelta(seconds=15))
                    )
                ).scalars().all()
                firing = (
                    await db.execute(select(AlertEvent.id).where(AlertEvent.state == AlertState.firing))
                ).scalars().all()
            frame = {
                "type": "tick",
                "ts": datetime.now(timezone.utc),
                "agents": [
                    {"id": a.id, "name": a.name, "online": is_online(a), "last_seen_at": a.last_seen_at}
                    for a in agents
                ],
                "alerts_firing": len(firing),
                # Current consumption, reported by agents every ≈2 s.
                "live": [
                    {
                        "agent_id": r.agent_id,
                        "ts": r.ts,
                        "rx_bps": r.rx_bps,
                        "tx_bps": r.tx_bps,
                        "interfaces": r.interfaces if r.agent_id == current_focus else None,
                    }
                    for r in live_rows
                ],
                "metrics": [
                    {
                        "agent_id": m.agent_id,
                        "ts": m.ts,
                        "cpu_percent": m.cpu_percent,
                        "mem_percent": m.mem_percent,
                        "load1": m.load1,
                        "rx_bps": m.rx_bps,
                        "tx_bps": m.tx_bps,
                        "tcp_established": m.tcp_established,
                    }
                    for m in metrics
                ],
                "interfaces": [
                    {
                        "agent_id": i.agent_id,
                        "ts": i.ts,
                        "iface": i.iface,
                        "rx_bps": i.rx_bps,
                        "tx_bps": i.tx_bps,
                        "rx_pps": i.rx_pps,
                        "tx_pps": i.tx_pps,
                    }
                    for i in ifaces
                ],
            }
            await ws.send_text(json.dumps(frame, default=_json_default))
            await asyncio.sleep(POLL_SECONDS)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        recv_task.cancel()
