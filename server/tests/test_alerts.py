from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from conftest import enroll_agent

from ipf3_server import worker
from ipf3_server.services import alerting

FX = Path(__file__).parent / "fixtures"


async def push_cpu(anon, headers, values, start):
    for i, v in enumerate(values):
        await anon.post("/api/agent/v1/metrics", headers=headers, json={
            "ts": (start + timedelta(seconds=10 * i)).isoformat(), "system": {"cpu_percent": v}, "interfaces": []})


async def test_cpu_alert_fires_and_resolves(admin, anon, viewer, operator, monkeypatch):
    sent = []

    async def fake_notify(transitions, names):
        sent.extend((ev.message, t) for ev, t in transitions)

    monkeypatch.setattr(alerting, "notify", fake_notify)
    agent_id, headers = await enroll_agent(admin, anon)
    r = await admin.post("/api/v1/alerts/rules", json={"name": "High CPU", "metric": "cpu_percent", "operator": ">",
                                                       "threshold": 80, "for_seconds": 60, "severity": "critical",
                                                       "webhook_url": "https://hooks.example.com/x"})
    assert r.status_code == 201, r.text
    now = datetime.now(timezone.utc)
    await push_cpu(anon, headers, [95, 50, 96], now - timedelta(seconds=30))
    assert await worker.evaluate_alerts() == 0  # one dip below threshold => not sustained
    await push_cpu(anon, headers, [97, 98, 99, 97, 96, 95, 99], now - timedelta(seconds=55) + timedelta(minutes=2))
    assert await worker.evaluate_alerts(now + timedelta(minutes=2, seconds=10)) == 1
    assert sent[0][1] == "firing" and "High CPU" in sent[0][0]
    events = (await viewer.get("/api/v1/alerts/events", params={"state": "firing"})).json()
    assert len(events) == 1 and events[0]["agent_name"] == "edge-1" and events[0]["severity"] == "critical"
    # Still firing: no duplicate event.
    assert await worker.evaluate_alerts(now + timedelta(minutes=2, seconds=15)) == 0
    r = await operator.post(f"/api/v1/alerts/events/{events[0]['id']}/ack")
    assert r.json()["acknowledged_by"] is not None
    await push_cpu(anon, headers, [10] * 7, now + timedelta(minutes=5))
    assert await worker.evaluate_alerts(now + timedelta(minutes=6, seconds=5)) == 1
    assert sent[-1][1] == "resolved"


async def test_offline_alert(admin, anon, monkeypatch):
    monkeypatch.setattr(alerting, "notify", lambda *a: _noop())
    await enroll_agent(admin, anon)
    await admin.post("/api/v1/alerts/rules", json={"name": "Offline", "metric": "agent_offline", "operator": ">", "threshold": 120})
    assert await worker.evaluate_alerts() == 0
    assert await worker.evaluate_alerts(datetime.now(timezone.utc) + timedelta(minutes=5)) == 1


async def _noop():
    return None


async def test_ping_loss_alert_scoped_to_target(admin, anon, operator, monkeypatch):
    monkeypatch.setattr(alerting, "notify", lambda *a: _noop())
    agent_id, headers = await enroll_agent(admin, anon)
    await admin.post("/api/v1/alerts/rules", json={"name": "Loss", "metric": "ping_loss_percent", "operator": ">=",
                                                   "threshold": 10, "agent_id": agent_id, "target": "1.1.1.1"})
    job_id = (await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "ping", "params": {"target": "1.1.1.1"}})).json()["id"]
    await anon.get("/api/agent/v1/jobs", headers=headers)
    await anon.post(f"/api/agent/v1/jobs/{job_id}/result", headers=headers, json={"status": "completed", "raw": (FX / "ping_ok.txt").read_text()})
    assert await worker.evaluate_alerts() == 1


async def test_rule_validation(admin, operator):
    r = await admin.post("/api/v1/alerts/rules", json={"name": "x", "metric": "nope", "operator": ">", "threshold": 1})
    assert r.status_code == 422
    r = await admin.post("/api/v1/alerts/rules", json={"name": "x", "metric": "cpu_percent", "operator": ">", "threshold": 1, "webhook_url": "file:///etc/passwd"})
    assert r.status_code == 422
    r = await operator.post("/api/v1/alerts/rules", json={"name": "x", "metric": "cpu_percent", "operator": ">", "threshold": 1})
    assert r.status_code == 403


async def test_webhook_payload(monkeypatch):
    captured = {}

    def handler(request: httpx.Request):
        import json

        captured.update(json.loads(request.content))
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    monkeypatch.setattr(alerting.httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
    from ipf3_server.models import AlertEvent, AlertRule, AlertState, Severity

    rule = AlertRule(id=1, name="High CPU", metric="cpu_percent", operator=">", threshold=80, webhook_url="https://h.example/x")
    ev = AlertEvent(id=7, rule_id=1, agent_id="a", state=AlertState.firing, severity=Severity.critical, value=91.0,
                    message="High CPU: cpu_percent on edge-1 is 91.00 (> 80.00)", started_at=datetime.now(timezone.utc))
    ev.rule = rule
    await alerting.notify([(ev, "firing")], {"a": "edge-1"})
    assert captured["status"] == "firing" and captured["agent"]["name"] == "edge-1"
    assert captured["text"].startswith("[FIRING] [CRITICAL]")
