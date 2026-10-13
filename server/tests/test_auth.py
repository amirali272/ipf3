from conftest import ADMIN_PW, login


async def test_login_sets_cookies_and_me(admin):
    r = await admin.get("/api/v1/auth/me")
    assert r.status_code == 200
    assert r.json()["username"] == "admin"
    assert r.json()["role"] == "admin"


async def test_unauthenticated(anon):
    assert (await anon.get("/api/v1/agents")).status_code == 401
    assert (await anon.get("/api/v1/auth/me")).status_code == 401


async def test_bad_password_and_lockout(anon):
    for _ in range(5):
        r = await anon.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 401
    # Now locked even with the right password.
    r = await anon.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 401


async def test_csrf_required_for_cookie_mutations(admin):
    del admin.headers["x-ipf3-csrf"]
    r = await admin.post("/api/v1/enrollment-tokens", json={"note": "x"})
    assert r.status_code == 403
    admin.headers["x-ipf3-csrf"] = "forged"
    r = await admin.post("/api/v1/enrollment-tokens", json={"note": "x"})
    assert r.status_code == 403


async def test_change_password_invalidates_old_sessions(app, admin):
    import httpx

    old_cookie = admin.cookies.get("ipf3_session")
    r = await admin.post("/api/v1/auth/change-password", json={"current_password": ADMIN_PW, "new_password": "short"})
    assert r.status_code == 422
    r = await admin.post(
        "/api/v1/auth/change-password",
        json={"current_password": ADMIN_PW, "new_password": "N3w-Very-Strong-Pass"},
    )
    assert r.status_code == 204
    assert (await admin.get("/api/v1/auth/me")).status_code == 200  # new cookie issued
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        c.cookies.set("ipf3_session", old_cookie)
        assert (await c.get("/api/v1/auth/me")).status_code == 401


async def test_rbac(viewer, operator, admin):
    assert (await viewer.get("/api/v1/agents")).status_code == 200
    assert (await viewer.get("/api/v1/users")).status_code == 403
    assert (await viewer.post("/api/v1/jobs", json={"agent_id": "x", "type": "ping", "params": {"target": "1.1.1.1"}})).status_code == 403
    assert (await operator.get("/api/v1/users")).status_code == 403
    assert (await operator.post("/api/v1/enrollment-tokens", json={})).status_code == 403
    assert (await operator.get("/api/v1/audit")).status_code == 403
    assert (await admin.get("/api/v1/audit")).status_code == 200


async def test_user_management(admin, anon):
    r = await admin.post("/api/v1/users", json={"username": "alice", "password": "weak", "role": "viewer"})
    assert r.status_code == 422
    r = await admin.post("/api/v1/users", json={"username": "alice", "password": "Al1ce-Strong-Pass", "role": "operator"})
    assert r.status_code == 201
    uid = r.json()["id"]
    r = await admin.post("/api/v1/users", json={"username": "alice", "password": "Al1ce-Strong-Pass"})
    assert r.status_code == 409
    await login(anon, "alice", "Al1ce-Strong-Pass")
    r = await admin.patch(f"/api/v1/users/{uid}", json={"is_active": False})
    assert r.status_code == 200
    assert (await anon.get("/api/v1/auth/me")).status_code == 401
    me = (await admin.get("/api/v1/auth/me")).json()
    assert (await admin.delete(f"/api/v1/users/{me['id']}")).status_code == 409
    assert (await admin.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"})).status_code == 409
