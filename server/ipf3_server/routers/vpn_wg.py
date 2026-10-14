"""WireGuard inbounds (one `wg0` per node) and peers."""

from __future__ import annotations

import ipaddress
import os
import base64
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import audit, require_admin, require_operator, require_viewer
from ..models import Agent, AgentInventory, User, VpnUser, WgInbound, WgNodeState, WgPeer, XrayInbound
from ..services import wireguard as wgsvc
from ..vpn_schemas import WgInboundIn, WgInboundOut, WgPeerConfig, WgPeerIn, WgPeerOut
from .agents import is_online

router = APIRouter(prefix="/vpn/wg", tags=["vpn"])

ONLINE_WINDOW = timedelta(minutes=3)  # a bit over 2x the default keepalive


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_inbound(db: AsyncSession, agent_id: str) -> WgInbound:
    row = await db.get(WgInbound, agent_id)
    if row is None:
        raise HTTPException(404, "No WireGuard inbound on this node")
    return row


async def _port_conflict(db: AsyncSession, agent_id: str, port: int) -> bool:
    """True when something else on the node already listens on this UDP/TCP port."""
    from .vpn import _LISTEN_STATES  # reuse the inventory-scan constant

    inv = await db.get(AgentInventory, agent_id)
    for c in (inv.connections if inv else []) or []:
        if c.get("state") not in _LISTEN_STATES:
            continue
        local = str(c.get("local", ""))
        if local.rsplit(":", 1)[-1] == str(port) and not local.startswith(("127.", "[::1]", "::1")):
            return True
    xray_hit = (
        await db.execute(select(XrayInbound.id).where(XrayInbound.agent_id == agent_id, XrayInbound.port == port))
    ).first()
    return xray_hit is not None


def _inbound_out(i: WgInbound, name: str, node_online: bool, st: WgNodeState | None, peer_count: int, online_count: int, up: int, down: int, in_sync: bool = False) -> WgInboundOut:
    return WgInboundOut(
        agent_id=i.agent_id, agent_name=name, online=node_online, remark=i.remark, listen_port=i.listen_port, network=i.network,
        address=i.address, dns=i.dns, mtu=i.mtu, persistent_keepalive=i.persistent_keepalive, egress_iface=i.egress_iface,
        public_key=i.public_key, enabled=i.enabled, created_at=i.created_at, peers=peer_count, online_peers=online_count,
        up=up, down=down, running=bool(st and st.running), error=st.error if st else None,
        in_sync=in_sync, applied_at=st.applied_at if st else None,
    )


@router.get("/inbounds", response_model=list[WgInboundOut])
async def list_inbounds(_: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    rows = (await db.execute(select(WgInbound))).scalars().all()
    agents = {a.id: a for a in (await db.execute(select(Agent))).scalars()}
    states = {s.agent_id: s for s in (await db.execute(select(WgNodeState))).scalars()}
    peers = (await db.execute(select(WgPeer))).scalars().all()
    by_agent: dict[str, list[WgPeer]] = {}
    for p in peers:
        by_agent.setdefault(p.agent_id, []).append(p)
    now = _now()
    out = []
    for i in rows:
        own = by_agent.get(i.agent_id, [])
        online = sum(1 for p in own if p.last_handshake_at and now - p.last_handshake_at < ONLINE_WINDOW)
        st = states.get(i.agent_id)
        desired_hash = wgsvc.config_hash(wgsvc.build_server_config(i, own))
        out.append(
            WgInboundOut(
                agent_id=i.agent_id, agent_name=agents[i.agent_id].name if i.agent_id in agents else i.agent_id,
                online=is_online(agents[i.agent_id]) if i.agent_id in agents else False, remark=i.remark, listen_port=i.listen_port,
                network=i.network, address=i.address, dns=i.dns, mtu=i.mtu, persistent_keepalive=i.persistent_keepalive,
                egress_iface=i.egress_iface, public_key=i.public_key, enabled=i.enabled, created_at=i.created_at,
                peers=len(own), online_peers=online, up=sum(p.up for p in own), down=sum(p.down for p in own),
                running=bool(st and st.running), error=st.error if st else None,
                in_sync=bool(st and st.applied_hash == desired_hash), applied_at=st.applied_at if st else None,
            )
        )
    return out


@router.post("/inbounds", response_model=WgInboundOut, status_code=201)
async def create_inbound(body: WgInboundIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    if await db.get(Agent, body.agent_id) is None:
        raise HTTPException(404, "Node not found")
    if await db.get(WgInbound, body.agent_id) is not None:
        raise HTTPException(409, "This node already has a WireGuard inbound — edit or delete it first")
    if await _port_conflict(db, body.agent_id, body.listen_port):
        raise HTTPException(409, f"Port {body.listen_port} is already in use on this node")
    egress = body.egress_iface
    if not egress:
        inv = await db.get(AgentInventory, body.agent_id)
        egress = wgsvc.detect_egress_iface(inv.routes if inv else []) or ""
    priv, pub = wgsvc.generate_keypair()
    row = WgInbound(
        agent_id=body.agent_id, remark=body.remark, listen_port=body.listen_port, network=body.network, address=body.address,
        dns=body.dns, mtu=body.mtu, persistent_keepalive=body.persistent_keepalive, egress_iface=egress,
        private_key=priv, public_key=pub, enabled=body.enabled,
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(409, "This node already has a WireGuard inbound") from e
    await audit(db, request, admin, "vpn.wg.inbound.create", body.remark, agent_id=body.agent_id, port=body.listen_port)
    await db.commit()
    agent = await db.get(Agent, row.agent_id)
    return _inbound_out(row, agent.name, is_online(agent), None, 0, 0, 0, 0)


@router.put("/inbounds/{agent_id}", response_model=WgInboundOut)
async def update_inbound(agent_id: str, body: WgInboundIn, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await _get_inbound(db, agent_id)
    if body.agent_id != agent_id:
        raise HTTPException(422, "Moving a WireGuard inbound to another node is not supported — delete and recreate it")
    if body.listen_port != row.listen_port and await _port_conflict(db, agent_id, body.listen_port):
        raise HTTPException(409, f"Port {body.listen_port} is already in use on this node")
    peers = (await db.execute(select(WgPeer).where(WgPeer.agent_id == agent_id))).scalars().all()
    if body.network != row.network:
        net = ipaddress.ip_network(body.network, strict=False)
        if any(ipaddress.ip_address(p.address) not in net for p in peers):
            raise HTTPException(409, "Existing peers have addresses outside the new network — remove them first")
    for f in ("remark", "listen_port", "network", "address", "dns", "mtu", "persistent_keepalive", "egress_iface", "enabled"):
        setattr(row, f, getattr(body, f))
    await audit(db, request, admin, "vpn.wg.inbound.update", row.remark, agent_id=agent_id)
    await db.commit()
    agent = await db.get(Agent, agent_id)
    st = await db.get(WgNodeState, agent_id)
    online = sum(1 for p in peers if p.last_handshake_at and _now() - p.last_handshake_at < ONLINE_WINDOW)
    desired_hash = wgsvc.config_hash(wgsvc.build_server_config(row, peers))
    in_sync = bool(st and st.applied_hash == desired_hash)
    return _inbound_out(row, agent.name, is_online(agent), st, len(peers), online, sum(p.up for p in peers), sum(p.down for p in peers), in_sync)


@router.delete("/inbounds/{agent_id}", status_code=204)
async def delete_inbound(agent_id: str, request: Request, admin: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    row = await _get_inbound(db, agent_id)
    await audit(db, request, admin, "vpn.wg.inbound.delete", row.remark, agent_id=agent_id)
    await db.delete(row)
    await db.commit()


@router.get("/inbounds/{agent_id}/peers", response_model=list[WgPeerOut])
async def list_peers(agent_id: str, _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    await _get_inbound(db, agent_id)
    rows = (await db.execute(select(WgPeer).where(WgPeer.agent_id == agent_id))).scalars().all()
    names = dict((await db.execute(select(VpnUser.id, VpnUser.username))).all())
    now = _now()
    return [
        WgPeerOut(
            id=p.id, agent_id=p.agent_id, user_id=p.user_id, username=names.get(p.user_id, "—"), address=p.address,
            enabled=p.enabled, up=p.up, down=p.down, online=bool(p.last_handshake_at and now - p.last_handshake_at < ONLINE_WINDOW),
            last_handshake_at=p.last_handshake_at, created_at=p.created_at,
        )
        for p in rows
    ]


@router.post("/inbounds/{agent_id}/peers", response_model=WgPeerOut, status_code=201)
async def create_peer(agent_id: str, body: WgPeerIn, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    inbound = await _get_inbound(db, agent_id)
    if await db.get(VpnUser, body.user_id) is None:
        raise HTTPException(404, "User not found")
    existing = (await db.execute(select(WgPeer).where(WgPeer.agent_id == agent_id))).scalars().all()
    if any(p.user_id == body.user_id for p in existing):
        raise HTTPException(409, "This user already has a WireGuard peer on this node")
    try:
        address = wgsvc.next_free_address(inbound.network, {p.address for p in existing})
    except ValueError as e:
        raise HTTPException(409, str(e)) from None
    priv, pub = wgsvc.generate_keypair()
    psk = base64.b64encode(os.urandom(32)).decode()
    row = WgPeer(agent_id=agent_id, user_id=body.user_id, address=address, private_key=priv, public_key=pub, preshared_key=psk)
    db.add(row)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(409, "Could not allocate this peer — try again") from e
    await audit(db, request, op, "vpn.wg.peer.create", f"user {body.user_id}", agent_id=agent_id, peer_id=row.id)
    await db.commit()
    username = (await db.get(VpnUser, body.user_id)).username
    return WgPeerOut(
        id=row.id, agent_id=agent_id, user_id=row.user_id, username=username, address=row.address, enabled=True,
        up=0, down=0, online=False, last_handshake_at=None, created_at=row.created_at,
    )


async def _get_peer(db: AsyncSession, peer_id: int) -> WgPeer:
    row = await db.get(WgPeer, peer_id)
    if row is None:
        raise HTTPException(404, "Peer not found")
    return row


@router.get("/peers/{peer_id}/config", response_model=WgPeerConfig)
async def peer_config(peer_id: int, _: User = Depends(require_viewer), db: AsyncSession = Depends(get_session)):
    peer = await _get_peer(db, peer_id)
    inbound = await _get_inbound(db, peer.agent_id)
    text = wgsvc.peer_config(inbound, peer)
    return WgPeerConfig(config=text, qr_text=text)


@router.delete("/peers/{peer_id}", status_code=204)
async def delete_peer(peer_id: int, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    peer = await _get_peer(db, peer_id)
    await audit(db, request, op, "vpn.wg.peer.delete", f"user {peer.user_id}", agent_id=peer.agent_id, peer_id=peer_id)
    await db.delete(peer)
    await db.commit()


@router.patch("/peers/{peer_id}/toggle", response_model=WgPeerOut)
async def toggle_peer(peer_id: int, request: Request, op: User = Depends(require_operator), db: AsyncSession = Depends(get_session)):
    peer = await _get_peer(db, peer_id)
    peer.enabled = not peer.enabled
    await audit(db, request, op, "vpn.wg.peer.toggle", str(peer.enabled), agent_id=peer.agent_id, peer_id=peer_id)
    await db.commit()
    username = (await db.get(VpnUser, peer.user_id)).username
    now = _now()
    return WgPeerOut(
        id=peer.id, agent_id=peer.agent_id, user_id=peer.user_id, username=username, address=peer.address, enabled=peer.enabled,
        up=peer.up, down=peer.down, online=bool(peer.last_handshake_at and now - peer.last_handshake_at < ONLINE_WINDOW),
        last_handshake_at=peer.last_handshake_at, created_at=peer.created_at,
    )
