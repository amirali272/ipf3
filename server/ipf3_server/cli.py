"""ipf3-server command line: migrations, user bootstrap, serving."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent


def _alembic_config():
    from alembic.config import Config

    from .config import get_settings

    cfg = Config(str(PKG_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(PKG_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
    return cfg


def cmd_migrate(args) -> int:
    from alembic import command

    command.upgrade(_alembic_config(), args.revision)
    print(f"database migrated to {args.revision}")
    return 0


def cmd_db_current(_args) -> int:
    from alembic import command

    command.current(_alembic_config(), verbose=False)
    return 0


async def _create_user(username: str, password: str, role: str, update: bool) -> str:
    from sqlalchemy import select

    from .db import dispose_engine, sessionmaker
    from .models import Role, User
    from .security import hash_password, validate_password_strength

    validate_password_strength(password)
    try:
        async with sessionmaker()() as db:
            user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
            if user and not update:
                return f"user '{username}' already exists (use --update to reset the password)"
            if user is None:
                user = User(username=username, password_hash=hash_password(password), role=Role(role))
                db.add(user)
                msg = f"created {role} '{username}'"
            else:
                user.password_hash = hash_password(password)
                user.role = Role(role)
                user.is_active = True
                user.locked_until = None
                user.failed_logins = 0
                user.session_version += 1
                msg = f"updated {role} '{username}'"
            await db.commit()
            return msg
    finally:
        await dispose_engine()


async def _create_enrollment_token(note: str, ttl_hours: int) -> str:
    from datetime import datetime, timedelta, timezone

    from .db import dispose_engine, sessionmaker
    from .models import AuditLog, EnrollmentToken
    from .security import hash_token, random_token

    token = "ipf3e_" + random_token(32)
    try:
        async with sessionmaker()() as db:
            row = EnrollmentToken(
                token_hash=hash_token(token),
                note=note,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=ttl_hours),
            )
            db.add(row)
            db.add(AuditLog(action="enrollment_token.create", target=note[:255], details={"via": "cli", "ttl_hours": ttl_hours}))
            await db.commit()
    finally:
        await dispose_engine()
    return token


def cmd_create_enrollment_token(args) -> int:
    print(asyncio.run(_create_enrollment_token(args.note, args.ttl_hours)))
    return 0


def cmd_create_user(args) -> int:
    password = os.environ.get("IPF3_NEW_USER_PASSWORD") or ""
    if not password:
        if not sys.stdin.isatty():
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Password: ")
            if password != getpass.getpass("Repeat password: "):
                print("passwords do not match", file=sys.stderr)
                return 1
    try:
        print(asyncio.run(_create_user(args.username, password, args.role, args.update)))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args) -> int:
    import uvicorn

    uvicorn.run(
        "ipf3_server.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("IPF3_FORWARDED_ALLOW_IPS", "127.0.0.1"),
        server_header=False,
        log_level=args.log_level,
    )
    return 0


def cmd_worker(_args) -> int:
    from .worker import run

    run()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ipf3-server")
    sub = p.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("migrate", help="apply database migrations")
    m.add_argument("revision", nargs="?", default="head")
    m.set_defaults(fn=cmd_migrate)

    sub.add_parser("db-current", help="show current migration revision").set_defaults(fn=cmd_db_current)

    u = sub.add_parser("create-user", help="create or reset a user (password from stdin/prompt)")
    u.add_argument("username")
    u.add_argument("--role", choices=["admin", "operator", "viewer"], default="admin")
    u.add_argument("--update", action="store_true", help="reset password/role if the user exists")
    u.set_defaults(fn=cmd_create_user)

    t = sub.add_parser("create-enrollment-token", help="print a one-time agent enrollment token")
    t.add_argument("--note", default="cli")
    t.add_argument("--ttl-hours", type=int, default=24)
    t.set_defaults(fn=cmd_create_enrollment_token)

    s = sub.add_parser("serve", help="run the API server")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--workers", type=int, default=2)
    s.add_argument("--log-level", default="info")
    s.set_defaults(fn=cmd_serve)

    sub.add_parser("worker", help="run the background worker").set_defaults(fn=cmd_worker)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
