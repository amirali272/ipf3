from datetime import datetime, timedelta, timezone
from pathlib import Path

from conftest import enroll_agent

from ipf3_server import worker

FX = Path(__file__).parent / "fixtures"


async def test_enrollment_token_single_use(admin, anon):
    r = await admin.post("/api/v1/enrollment-tokens", json={"note": "t"})
    token = r.json()["token"]
    body = {"enrollment_token": token, "name": "a1", "system": {"hostname": "a1"}}
    assert (await anon.post("/api/agent/v1/enroll", json=body)).status_code == 201
    body["name"] = "a2"
    assert (await anon.post("/api/agent/v1/enroll", json=body)).status_code == 401
    tokens = (await admin.get("/api/v1/enrollment-tokens")).json()
    assert tokens[0]["used_at"] is not None and "token" not in tokens[0] or tokens[0]["token"] is None


async def test_agent_auth_rejects_bad_tokens(admin, anon):
    agent_id, headers = await enroll_agent(admin, anon)
    assert (await anon.post("/api/agent/v1/heartbeat", json={"system": {}}, headers=headers)).status_code == 204
    bad = {"Authorization": f"Bearer {agent_id}.wrong"}
    assert (await anon.post("/api/agent/v1/heartbeat", json={"system": {}}, headers=bad)).status_code == 401
    # Session cookies are not agent credentials.
    assert (await admin.post("/api/agent/v1/heartbeat", json={"system": {}})).status_code == 401
    # Rotation invalidates the old token.
    r = await admin.post(f"/api/v1/agents/{agent_id}/rotate-token")
    new = {"Authorization": f"Bearer {r.json()['agent_token']}"}
    assert (await anon.post("/api/agent/v1/heartbeat", json={"system": {}}, headers=headers)).status_code == 401
    assert (await anon.post("/api/agent/v1/heartbeat", json={"system": {}}, headers=new)).status_code == 204
    # Disabled agents are refused.
    await admin.patch(f"/api/v1/agents/{agent_id}", json={"disabled": True})
    assert (await anon.post("/api/agent/v1/heartbeat", json={"system": {}}, headers=new)).status_code == 403


async def test_metrics_ingest_and_query(admin, anon, viewer):
    agent_id, headers = await enroll_agent(admin, anon)
    now = datetime.now(timezone.utc)
    for i in range(6):
        r = await anon.post(
            "/api/agent/v1/metrics",
            headers=headers,
            json={
                "ts": (now - timedelta(seconds=10 * (5 - i))).isoformat(),
                "system": {"cpu_percent": 10.0 + i, "mem_percent": 40.0, "load1": 0.5},
                "interfaces": [
                    {"iface": "eth0", "rx_bps": 1e6 * (i + 1), "tx_bps": 2e6, "rx_pps": 100, "tx_pps": 50},
                    {"iface": "eth1", "rx_bps": 1e5, "tx_bps": 1e5},
                ],
            },
        )
        assert r.status_code == 204, r.text
    agents = (await viewer.get("/api/v1/agents")).json()
    assert agents[0]["online"] is True
    assert agents[0]["latest"]["cpu_percent"] == 15.0
    assert agents[0]["latest"]["rx_bps"] == 6e6 + 1e5
    r = await viewer.get(f"/api/v1/agents/{agent_id}/metrics", params={"bucket": 60})
    pts = r.json()["points"]
    assert r.json()["bucket"] == 60
    assert sum(1 for _ in pts) >= 1
    assert all(p["cpu_percent"] is not None for p in pts)
    r = await viewer.get(f"/api/v1/agents/{agent_id}/interfaces/metrics", params={"iface": "eth0", "bucket": 3600})
    pts = r.json()["points"]
    assert {p["iface"] for p in pts} == {"eth0"}
    assert sum(p["rx_bps"] for p in pts) / len(pts) > 0


async def test_inventory_upsert(admin, anon, viewer):
    agent_id, headers = await enroll_agent(admin, anon)
    inv = {"interfaces": [{"name": "eth0", "addresses": ["10.0.0.2/24"]}], "routes": [{"dst": "default", "gateway": "10.0.0.1"}],
           "connections": [], "dns": {"nameservers": ["127.0.0.53"]}, "system": {}}
    assert (await anon.post("/api/agent/v1/inventory", headers=headers, json=inv)).status_code == 204
    inv["routes"].append({"dst": "10.0.0.0/24", "dev": "eth0"})
    assert (await anon.post("/api/agent/v1/inventory", headers=headers, json=inv)).status_code == 204
    r = (await viewer.get(f"/api/v1/agents/{agent_id}/inventory")).json()
    assert len(r["routes"]) == 2 and r["dns"]["nameservers"] == ["127.0.0.53"]


async def test_job_lifecycle_iperf3(admin, anon, operator, viewer):
    agent_id, headers = await enroll_agent(admin, anon)
    r = await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "iperf3", "params": {"target": "10.0.0.3", "duration": 5}})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    assert r.json()["status"] == "queued"
    jobs = (await anon.get("/api/agent/v1/jobs", headers=headers)).json()
    assert [j["id"] for j in jobs] == [job_id]
    assert jobs[0]["params"]["port"] == 5201
    assert (await anon.get("/api/agent/v1/jobs", headers=headers)).json() == []  # claimed once
    raw = (FX / "iperf3_tcp.json").read_text()
    r = await anon.post(f"/api/agent/v1/jobs/{job_id}/result", headers=headers, json={"status": "completed", "raw": raw})
    assert r.status_code == 204
    j = (await viewer.get(f"/api/v1/jobs/{job_id}")).json()
    assert j["status"] == "completed"
    assert j["bps"] == 930_150_000.0 and j["retransmits"] == 4
    assert len(j["result"]["intervals"]) == 5
    r = await viewer.get("/api/v1/analytics/tests", params={"type": "iperf3", "agent_id": agent_id})
    assert r.json()["summary"]["completed"] == 1
    assert r.json()["points"][0]["bps_avg"] == 930_150_000.0


async def test_job_result_unparseable_marks_failed(admin, anon, operator, viewer):
    agent_id, headers = await enroll_agent(admin, anon)
    job_id = (await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "ping", "params": {"target": "1.1.1.1"}})).json()["id"]
    await anon.get("/api/agent/v1/jobs", headers=headers)
    await anon.post(f"/api/agent/v1/jobs/{job_id}/result", headers=headers, json={"status": "completed", "raw": "garbage"})
    j = (await viewer.get(f"/api/v1/jobs/{job_id}")).json()
    assert j["status"] == "failed" and "statistics" in j["error"]


async def test_job_other_agent_cannot_report(admin, anon, operator):
    a1, h1 = await enroll_agent(admin, anon, "a1")
    _, h2 = await enroll_agent(admin, anon, "a2")
    job_id = (await operator.post("/api/v1/jobs", json={"agent_id": a1, "type": "ping", "params": {"target": "1.1.1.1"}})).json()["id"]
    assert (await anon.get("/api/agent/v1/jobs", headers=h2)).json() == []
    await anon.get("/api/agent/v1/jobs", headers=h1)
    r = await anon.post(f"/api/agent/v1/jobs/{job_id}/result", headers=h2, json={"status": "completed", "raw": "x"})
    assert r.status_code == 404


async def test_job_validation_and_capabilities(admin, anon, operator):
    agent_id, _ = await enroll_agent(admin, anon, tools={"iperf3": True, "ping": True, "traceroute": True, "mtr": False, "dns": True})
    r = await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "ping", "params": {"target": "-c 1 x"}})
    assert r.status_code == 422
    r = await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "mtr", "params": {"target": "1.1.1.1"}})
    assert r.status_code == 409


async def test_cancel_and_late_result(admin, anon, operator, viewer):
    agent_id, headers = await enroll_agent(admin, anon)
    job_id = (await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "ping", "params": {"target": "1.1.1.1"}})).json()["id"]
    await anon.get("/api/agent/v1/jobs", headers=headers)
    assert (await operator.post(f"/api/v1/jobs/{job_id}/cancel")).json()["status"] == "cancelled"
    raw = (FX / "ping_ok.txt").read_text()
    await anon.post(f"/api/agent/v1/jobs/{job_id}/result", headers=headers, json={"status": "completed", "raw": raw})
    assert (await viewer.get(f"/api/v1/jobs/{job_id}")).json()["status"] == "cancelled"


async def test_schedules_create_jobs_without_stacking(admin, anon, operator):
    agent_id, headers = await enroll_agent(admin, anon)
    r = await operator.post("/api/v1/schedules", json={"name": "ping cf", "agent_id": agent_id, "type": "ping",
                                                         "params": {"target": "1.1.1.1", "count": 5}, "interval_seconds": 60})
    assert r.status_code == 201
    r = await operator.post("/api/v1/schedules", json={"name": "bw", "agent_id": agent_id, "type": "iperf3",
                                                         "params": {"target": "10.0.0.3"}, "interval_seconds": 60})
    assert r.status_code == 422
    assert await worker.run_schedules() == 1
    assert await worker.run_schedules() == 0  # interval not elapsed
    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    assert await worker.run_schedules(later) == 0  # previous run still queued
    jobs = (await anon.get("/api/agent/v1/jobs", headers=headers)).json()
    await anon.post(f"/api/agent/v1/jobs/{jobs[0]['id']}/result", headers=headers,
                    json={"status": "completed", "raw": (FX / "ping_ok.txt").read_text()})
    assert await worker.run_schedules(later) == 1


async def test_job_expiry(admin, anon, operator, viewer):
    agent_id, headers = await enroll_agent(admin, anon)
    job_id = (await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "ping", "params": {"target": "1.1.1.1"}})).json()["id"]
    assert await worker.expire_jobs(datetime.now(timezone.utc) + timedelta(hours=1)) == 1
    assert (await viewer.get(f"/api/v1/jobs/{job_id}")).json()["status"] == "expired"


async def test_retention(admin, anon):
    _, headers = await enroll_agent(admin, anon)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    await anon.post("/api/agent/v1/metrics", headers=headers, json={"ts": old.isoformat(), "system": {"cpu_percent": 1}, "interfaces": []})
    out = await worker.purge_old_data(datetime.now(timezone.utc) + timedelta(days=31))
    assert out["metric_samples"] == 1


async def test_audit_records_actions(admin, anon):
    await enroll_agent(admin, anon)
    actions = [a["action"] for a in (await admin.get("/api/v1/audit")).json()]
    assert "agent.enroll" in actions and "enrollment_token.create" in actions and "auth.login" in actions
