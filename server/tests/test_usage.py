from datetime import date, datetime, timedelta, timezone

from conftest import enroll_agent

from ipf3_server import worker


def _metrics(ts, ifaces):
    return {"ts": ts.isoformat(), "system": {"cpu_percent": 5}, "interfaces": ifaces}


async def test_usage_counts_bytes_on_primary_interfaces(admin, anon, viewer):
    agent_id, h = await enroll_agent(admin, anon)
    now = datetime.now(timezone.utc)
    for i in range(3):
        r = await anon.post("/api/agent/v1/metrics", headers=h, json=_metrics(now - timedelta(seconds=10 * i), [
            {"iface": "eth0", "rx_bps": 8000, "tx_bps": 16000, "rx_bytes": 10_000, "tx_bytes": 20_000, "primary": True},
            # virtual interfaces would double count: excluded from host totals
            {"iface": "docker0", "rx_bps": 8000, "tx_bps": 8000, "rx_bytes": 9_999, "tx_bytes": 9_999, "primary": False},
        ]))
        assert r.status_code == 204, r.text
    u = (await viewer.get("/api/v1/analytics/usage", params={"days": 7})).json()
    assert u["fleet"]["today_rx"] == 30_000 and u["fleet"]["today_tx"] == 60_000
    assert u["fleet"]["month_rx"] >= 30_000
    assert u["agents"][0]["name"] == "edge-1"
    assert len(u["daily"]) == 1 and u["daily"][-1]["rx_bytes"] == 30_000
    per_iface = (await viewer.get("/api/v1/analytics/usage", params={"agent_id": agent_id, "iface": "docker0"})).json()
    assert per_iface["fleet"]["today_rx"] == 29_997
    agents = (await viewer.get("/api/v1/agents")).json()
    assert agents[0]["latest"]["rx_bps"] == 8000  # host total = primary only


async def test_fleet_bandwidth_sums_agents(admin, anon, viewer):
    _, h1 = await enroll_agent(admin, anon, "a1")
    _, h2 = await enroll_agent(admin, anon, "a2")
    now = datetime.now(timezone.utc)
    for h, rx in ((h1, 1e6), (h2, 3e6)):
        await anon.post("/api/agent/v1/metrics", headers=h, json=_metrics(now, [{"iface": "eth0", "rx_bps": rx, "tx_bps": 0, "primary": True}]))
    r = (await viewer.get("/api/v1/analytics/fleet-bandwidth", params={"bucket": 3600})).json()
    assert sum(p["rx_bps"] for p in r["points"]) == 4e6


async def test_live_rates(admin, anon, viewer):
    agent_id, h = await enroll_agent(admin, anon)
    body = {"interfaces": [{"iface": "eth0", "rx_bps": 5e6, "tx_bps": 1e6, "primary": True},
                           {"iface": "wg0", "rx_bps": 4e6, "tx_bps": 1e6, "primary": False}]}
    assert (await anon.post("/api/agent/v1/live", headers=h, json=body)).status_code == 204
    body["interfaces"][0]["rx_bps"] = 7e6
    assert (await anon.post("/api/agent/v1/live", headers=h, json=body)).status_code == 204
    live = (await viewer.get("/api/v1/analytics/live")).json()
    assert live == [{"agent_id": agent_id, "ts": live[0]["ts"], "rx_bps": 7e6, "tx_bps": 1e6, "interfaces": body["interfaces"]}]
    assert (await anon.post("/api/agent/v1/live", json=body)).status_code == 401


async def test_usage_retention(admin, anon):
    agent_id, h = await enroll_agent(admin, anon)
    await anon.post("/api/agent/v1/metrics", headers=h, json=_metrics(datetime.now(timezone.utc), [
        {"iface": "eth0", "rx_bps": 1, "tx_bps": 1, "rx_bytes": 1, "tx_bytes": 1, "primary": True}]))
    out = await worker.purge_old_data(datetime.now(timezone.utc) + timedelta(days=40))
    assert out["traffic_daily"] == 0  # usage outlives raw samples
    assert out["metric_samples"] == 1
    out = await worker.purge_old_data(datetime.now(timezone.utc) + timedelta(days=1200))
    assert out["traffic_daily"] == 2


async def test_system_status(viewer):
    s = (await viewer.get("/api/v1/system/status")).json()
    assert s["api"] and s["database"] and s["worker"] is False
    assert s["mem_percent"] is not None and s["version"]


def test_usage_day_timezone(monkeypatch):
    from ipf3_server.services import usage

    usage.usage_tz.cache_clear()
    monkeypatch.setattr(usage, "get_settings", lambda: type("S", (), {"usage_timezone": "Asia/Tehran"})())
    try:
        # 21:00 UTC is 00:30 next day in Tehran (UTC+03:30)
        assert usage.usage_day(datetime(2026, 10, 13, 21, 0, tzinfo=timezone.utc)) == date(2026, 10, 14)
    finally:
        usage.usage_tz.cache_clear()
