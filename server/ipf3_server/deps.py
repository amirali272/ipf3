from __future__ import annotations

import ipaddress
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .models import Agent, AuditLog, Role, User
from .security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    ROLE_LEVEL,
    SESSION_COOKIE,
    decode_session_token,
    hash_token,
    tokens_equal,
)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def client_ip(request: Request) -> str:
    """Return the client address, honouring X-Forwarded-For only when the direct
    peer is a configured trusted reverse proxy."""
    peer = request.client.host if request.client else ""
    trusted = get_settings().trusted_proxies
    try:
        peer_trusted = any(
            ipaddress.ip_address(peer) in ipaddress.ip_network(t, strict=False) for t in trusted
        )
    except ValueError:
        peer_trusted = False
    if peer_trusted:
        xff = request.headers.get("x-forwarded-for")
        if xff:
            # Right-most address not belonging to a trusted proxy.
            for addr in reversed([a.strip() for a in xff.split(",") if a.strip()]):
                try:
                    ip = ipaddress.ip_address(addr)
                except ValueError:
                    break
                if not any(ip in ipaddress.ip_network(t, strict=False) for t in trusted):
                    return addr
    return peer


async def _user_from_request(request: Request, db: AsyncSession) -> User | None:
    token = None
    via_cookie = False
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    else:
        token = request.cookies.get(SESSION_COOKIE)
        via_cookie = token is not None
    if not token:
        return None
    payload = decode_session_token(token)
    if payload is None:
        return None
    if via_cookie and request.method not in SAFE_METHODS:
        # Double-submit CSRF protection for cookie-authenticated mutations.
        header = request.headers.get(CSRF_HEADER, "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        if not header or not cookie or not tokens_equal(header, cookie):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF token missing or invalid")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active or user.session_version != payload["sv"]:
        return None
    return user


async def current_user(request: Request, db: AsyncSession = Depends(get_session)) -> User:
    user = await _user_from_request(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    request.state.user = user
    return user


def require_role(minimum: Role) -> Callable:
    async def dep(user: User = Depends(current_user)) -> User:
        if ROLE_LEVEL[user.role] < ROLE_LEVEL[minimum]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user

    return dep


require_viewer = require_role(Role.viewer)
require_operator = require_role(Role.operator)
require_admin = require_role(Role.admin)


async def current_agent(request: Request, db: AsyncSession = Depends(get_session)) -> Agent:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing agent credentials")
    token = auth[7:].strip()
    agent_id, _, secret = token.partition(".")
    if not agent_id or not secret or len(agent_id) > 36:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed agent credentials")
    agent = await db.get(Agent, agent_id)
    if agent is None or not tokens_equal(agent.token_hash, hash_token(secret)):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid agent credentials")
    if agent.disabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Agent disabled")
    agent.last_seen_at = datetime.now(timezone.utc)
    agent.remote_addr = client_ip(request)[:64]
    return agent


async def audit(
    db: AsyncSession,
    request: Request | None,
    user: User | None,
    action: str,
    target: str = "",
    **details,
) -> None:
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            username=user.username if user else "",
            action=action,
            target=target[:255],
            details=details,
            ip=client_ip(request) if request else None,
        )
    )
