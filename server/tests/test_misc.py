async def test_health(anon):
    assert (await anon.get("/healthz")).json()["status"] == "ok"
    assert (await anon.get("/readyz")).status_code == 200


async def test_security_headers(anon):
    r = await anon.get("/healthz")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


async def test_payload_limit(anon):
    r = await anon.post("/api/agent/v1/metrics", content=b"x", headers={"content-length": str(50 * 1024 * 1024)})
    assert r.status_code == 413


async def test_overview(viewer):
    r = await viewer.get("/api/v1/analytics/overview")
    assert r.status_code == 200 and r.json()["agents_total"] == 0


async def test_time_range_validation(viewer, admin, anon):
    from conftest import enroll_agent

    agent_id, _ = await enroll_agent(admin, anon)
    r = await viewer.get(f"/api/v1/agents/{agent_id}/metrics", params={"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"})
    assert r.status_code == 422
