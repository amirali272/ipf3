from __future__ import annotations

import os
import secrets

os.environ.setdefault("IPF3_SECRET_KEY", secrets.token_hex(32))
os.environ.setdefault(
    "IPF3_DATABASE_URL",
    os.environ.get("IPF3_TEST_DATABASE_URL", "postgresql+asyncpg://postgres@127.0.0.1:5432/ipf3_test"),
)
os.environ["IPF3_COOKIE_SECURE"] = "false"
if os.environ.get("XRAY_BIN"):
    os.environ.setdefault("IPF3_XRAY_BIN", os.environ["XRAY_BIN"])
    os.environ.setdefault("IPF3_XRAY_ASSETS", os.path.dirname(os.environ["XRAY_BIN"]))

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from ipf3_server.cli import _alembic_config  # noqa: E402
from ipf3_server.db import dispose_engine, get_engine, sessionmaker  # noqa: E402
from ipf3_server.main import create_app  # noqa: E402
from ipf3_server.models import Base, Role, User  # noqa: E402
from ipf3_server.security import CSRF_COOKIE, hash_password  # noqa: E402
from ipf3_server.services.ratelimit import enroll_limiter, login_limiter  # noqa: E402

ADMIN_PW = "Adm1n-Passw0rd!"
OPER_PW = "0perator-Passw0rd!"
VIEW_PW = "V1ewer-Passw0rd!"


@pytest.fixture(scope="session", autouse=True)
async def database():
    async with get_engine().begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await dispose_engine()
    from alembic import command

    import asyncio

    await asyncio.to_thread(command.upgrade, _alembic_config(), "head")
    yield
    await dispose_engine()


@pytest.fixture(autouse=True)
async def clean(database):
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    async with sessionmaker()() as db:
        db.add_all(
            [
                User(username="admin", password_hash=hash_password(ADMIN_PW), role=Role.admin),
                User(username="oper", password_hash=hash_password(OPER_PW), role=Role.operator),
                User(username="viewer", password_hash=hash_password(VIEW_PW), role=Role.viewer),
            ]
        )
        await db.commit()
    login_limiter._events.clear()
    enroll_limiter._events.clear()
    yield


@pytest.fixture(scope="session")
def app():
    return create_app()


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def login(client: httpx.AsyncClient, username: str, password: str) -> httpx.AsyncClient:
    r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    client.headers["x-ipf3-csrf"] = client.cookies.get(CSRF_COOKIE)
    return client


@pytest.fixture
async def anon(app):
    async with _client(app) as c:
        yield c


@pytest.fixture
async def admin(app):
    async with _client(app) as c:
        yield await login(c, "admin", ADMIN_PW)


@pytest.fixture
async def operator(app):
    async with _client(app) as c:
        yield await login(c, "oper", OPER_PW)


@pytest.fixture
async def viewer(app):
    async with _client(app) as c:
        yield await login(c, "viewer", VIEW_PW)


async def enroll_agent(admin: httpx.AsyncClient, anon: httpx.AsyncClient, name: str = "edge-1", tools=None):
    r = await admin.post("/api/v1/enrollment-tokens", json={"note": name})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    caps = {"tools": tools or {"iperf3": True, "ping": True, "traceroute": True, "mtr": True, "dns": True}}
    r = await anon.post(
        "/api/agent/v1/enroll",
        json={
            "enrollment_token": token,
            "name": name,
            "system": {"hostname": name, "os_name": "Ubuntu 24.04 LTS", "kernel": "6.8.0", "agent_version": "1.0.0", "cpu_count": 4, "capabilities": caps},
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return body["agent_id"], {"Authorization": f"Bearer {body['agent_token']}"}
