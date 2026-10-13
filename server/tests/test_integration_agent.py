"""Runs the real ipf3-agent code against the real API (in-process ASGI) and,
when the tools are installed, real ping / iperf3 executions."""

import asyncio
import shutil
import socket
import subprocess

import httpx
import pytest
from conftest import enroll_agent

agent_mod = pytest.importorskip("ipf3_agent.runner")
from ipf3_agent.config import AgentConfig  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _make_agent(app, admin, anon, monkeypatch):
    monkeypatch.setenv("IPF3_AGENT_ALLOW_HTTP", "1")
    agent_id, headers = await enroll_agent(admin, anon, "integration")
    cfg = AgentConfig(server_url="http://test", agent_id=agent_id, agent_token=headers["Authorization"][7:])
    a = agent_mod.Agent(cfg)
    await a.client.aclose()
    a.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/agent/v1", headers=headers)
    return agent_id, a


async def _run_one_job(a) -> None:
    r = await a._request("GET", "/jobs", params={"wait": 0})
    jobs = r.json()
    assert len(jobs) == 1
    await a._run_job(jobs[0])


async def test_agent_telemetry_roundtrip(app, admin, anon, viewer, monkeypatch):
    agent_id, a = await _make_agent(app, admin, anon, monkeypatch)
    await a.send_heartbeat()
    await a.send_metrics()  # primes counters, sends nothing
    await asyncio.sleep(1.1)
    await a.send_metrics()
    await a.send_inventory()
    await a.client.aclose()
    agent = (await viewer.get(f"/api/v1/agents/{agent_id}")).json()
    assert agent["online"] and agent["latest"]["mem_percent"] > 0
    assert agent["capabilities"]["tools"]["dns"] is True
    inv = (await viewer.get(f"/api/v1/agents/{agent_id}/inventory")).json()
    assert inv["system"]["cpu_count"] >= 1


@pytest.mark.skipif(shutil.which("ping") is None, reason="ping not installed")
async def test_agent_runs_real_ping(app, admin, anon, operator, viewer, monkeypatch):
    agent_id, a = await _make_agent(app, admin, anon, monkeypatch)
    r = await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "ping", "params": {"target": "127.0.0.1", "count": 3, "interval": 0.2}})
    job_id = r.json()["id"]
    await _run_one_job(a)
    await a.client.aclose()
    j = (await viewer.get(f"/api/v1/jobs/{job_id}")).json()
    if j["status"] == "failed" and "Operation not permitted" in (j["error"] or "") + (j["raw"] or ""):
        pytest.skip("ICMP sockets not permitted in this environment")
    assert j["status"] == "completed", j
    assert j["loss_percent"] == 0.0 and j["rtt_avg_ms"] is not None
    assert len(j["result"]["replies"]) == 3


@pytest.mark.skipif(shutil.which("iperf3") is None, reason="iperf3 not installed")
async def test_agent_runs_real_iperf3(app, admin, anon, operator, viewer, monkeypatch):
    port = _free_port()
    server = subprocess.Popen(["iperf3", "-s", "-1", "-B", "127.0.0.1", "-p", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await asyncio.sleep(0.5)
        agent_id, a = await _make_agent(app, admin, anon, monkeypatch)
        r = await operator.post("/api/v1/jobs", json={"agent_id": agent_id, "type": "iperf3",
                                                      "params": {"target": "127.0.0.1", "port": port, "duration": 2, "protocol": "udp", "bitrate_bps": 20_000_000}})
        job_id = r.json()["id"]
        await _run_one_job(a)
        await a.client.aclose()
    finally:
        server.kill()
        server.wait()
    j = (await viewer.get(f"/api/v1/jobs/{job_id}")).json()
    assert j["status"] == "completed", j
    assert 15_000_000 < j["bps"] < 25_000_000
    assert j["jitter_ms"] is not None and j["loss_percent"] is not None
    assert len(j["result"]["intervals"]) >= 2
