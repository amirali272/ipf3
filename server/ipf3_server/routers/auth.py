from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_session
from ..deps import audit, client_ip, current_user
from ..models import User
from ..schemas import ChangePasswordIn, LoginIn, UserOut
from ..security import (
    CSRF_COOKIE,
    SESSION_COOKIE,
    create_session_token,
    hash_password,
    needs_rehash,
    random_token,
    validate_password_strength,
    verify_password,
)
from ..services.ratelimit import login_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, token: str, expires: datetime) -> None:
    s = get_settings()
    max_age = int((expires - datetime.now(timezone.utc)).total_seconds())
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        random_token(24),
        max_age=max_age,
        httponly=False,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/login", response_model=UserOut)
async def login(
    body: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_session)
):
    s = get_settings()
    ip = client_ip(request)
    if not login_limiter.allow(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts")

    user = (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if user is not None and user.locked_until and user.locked_until > now:
        verify_password(body.password, None)  # constant-ish timing
        await audit(db, request, user, "auth.login_locked", user.username)
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials or account locked")

    ok = verify_password(body.password, user.password_hash if user else None)
    if not ok or user is None or not user.is_active:
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= s.login_max_failures:
                user.locked_until = now + timedelta(minutes=s.login_lockout_minutes)
                user.failed_logins = 0
            await audit(db, request, user, "auth.login_failed", user.username)
        else:
            await audit(db, request, None, "auth.login_failed", body.username[:64])
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials or account locked")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    login_limiter.reset(ip)
    await audit(db, request, user, "auth.login", user.username)
    await db.commit()
    token, exp = create_session_token(user.id, user.session_version)
    _set_session_cookies(response, token, exp)
    return user


@router.post("/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return user


@router.post("/change-password", status_code=204)
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_session),
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    try:
        validate_password_strength(body.new_password)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    user = await db.merge(user)
    user.password_hash = hash_password(body.new_password)
    user.session_version += 1
    await audit(db, request, user, "auth.change_password", user.username)
    await db.commit()
    token, exp = create_session_token(user.id, user.session_version)
    _set_session_cookies(response, token, exp)
