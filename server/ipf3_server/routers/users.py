from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import audit, require_admin
from ..models import Role, User
from ..schemas import UserCreate, UserOut, UserUpdate
from ..security import hash_password, validate_password_strength

router = APIRouter(prefix="/users", tags=["users"])


def _check_password(pw: str) -> None:
    try:
        validate_password_strength(pw)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


async def _active_admins(db: AsyncSession) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(User).where(User.role == Role.admin, User.is_active)
        )
    ).scalar_one()


@router.get("", response_model=list[UserOut])
async def list_users(_: User = Depends(require_admin), db: AsyncSession = Depends(get_session)):
    return (await db.execute(select(User).order_by(User.username))).scalars().all()


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    _check_password(body.password)
    user = User(
        username=body.username,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists") from e
    await audit(db, request, admin, "user.create", user.username, role=user.role.value)
    await db.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    changes: dict = {}
    demoting = (body.role is not None and body.role != Role.admin) or body.is_active is False
    if demoting and user.role == Role.admin and user.is_active and await _active_admins(db) <= 1:
        raise HTTPException(409, "Cannot demote or deactivate the last active admin")
    if body.email is not None:
        user.email = body.email
        changes["email"] = body.email
    if body.role is not None and body.role != user.role:
        user.role = body.role
        user.session_version += 1
        changes["role"] = body.role.value
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        user.session_version += 1
        changes["is_active"] = body.is_active
    if body.password:
        _check_password(body.password)
        user.password_hash = hash_password(body.password)
        user.session_version += 1
        changes["password"] = "reset"
    if body.unlock:
        user.locked_until = None
        user.failed_logins = 0
        changes["unlock"] = True
    await audit(db, request, admin, "user.update", user.username, **changes)
    await db.commit()
    return user


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_session),
):
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == admin.id:
        raise HTTPException(409, "You cannot delete your own account")
    if user.role == Role.admin and user.is_active and await _active_admins(db) <= 1:
        raise HTTPException(409, "Cannot delete the last active admin")
    await audit(db, request, admin, "user.delete", user.username)
    await db.delete(user)
    await db.commit()
