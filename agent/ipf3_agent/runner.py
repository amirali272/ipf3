from __future__ import annotations

import asyncio
import logging
import random
import signal
import ssl
from datetime import datetime, timezone

import httpx

from . import __version__
from .collect import MetricsCollector, host_inventory, system_info
from .config import AgentConfig
from .tools import JobError, execute

log = logging.getLogger("ipf3.agent")


def make_client(server_url: str, ca_file: str | None, token: str | None = None) -> httpx.AsyncClient:
    verify: ssl.SSLContext | bool = True
    if ca_file:
        verify = ssl.create_default_context(cafile=ca_file)
    headers = {"User-Agent": f"ipf3-agent/{__version__}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(
        base_url=server_url.rstrip("/") + "/api/agent/v1",
        verify=verify,
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
    )


async def enroll(server_url: str, token: str, name: str, ca_file: str | None) -> tuple[str, str]:
    async with make_client(server_url, ca_file) as client:
        r = await client.post(
            "/enroll", json={"enrollment_token": token, "name": name, "system": system_info(name)}
        )
        if r.status_code != 201:
            raise RuntimeError(f"enrollment failed: HTTP {r.status_code}: {r.text[:500]}")
        body = r.json()
        return body["agent_id"], body["agent_token"]


class FatalAuthError(Exception):
    pass


class Agent:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.client = make_client(cfg.server_url, cfg.ca_file, cfg.agent_token)
        self.collector = MetricsCollector(cfg.exclude_interfaces)
        self.stop = asyncio.Event()
        self.job_slots = asyncio.Semaphore(max(1, cfg.max_concurrent_jobs))
        # Bandwidth tests run one at a time so they do not distort each other.
        self.iperf_lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()

    async def _request(self, method: str, url: str, **kw) -> httpx.Response:
        r = await self.client.request(method, url, **kw)
        if r.status_code in (401, 403):
            raise FatalAuthError(f"server rejected agent credentials (HTTP {r.status_code}): {r.text[:200]}")
        r.raise_for_status()
        return r

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def _periodic(self, name: str, interval: float, fn) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            try:
                await fn()
                backoff = 1.0
                await self._sleep(interval)
            except FatalAuthError:
                raise
            except (httpx.HTTPError, OSError) as e:
                log.warning("%s failed: %s (retry in %.0fs)", name, e, backoff)
                await self._sleep(backoff)
                backoff = min(backoff * 2, 60.0)
            except Exception:  # noqa: BLE001
                log.exception("%s crashed", name)
                await self._sleep(interval)

    async def send_metrics(self) -> None:
        sample = await asyncio.to_thread(self.collector.sample)
        if sample is None:
            return
        sample["ts"] = datetime.now(timezone.utc).isoformat()
        await self._request("POST", "/metrics", json=sample)

    async def send_inventory(self) -> None:
        inv = await asyncio.to_thread(host_inventory, self.cfg.max_connections_reported)
        await self._request("POST", "/inventory", json=inv)

    async def send_heartbeat(self) -> None:
        await self._request("POST", "/heartbeat", json={"system": system_info(self.cfg.name)})

    async def _run_job(self, job: dict) -> None:
        job_id, jtype, params = job["id"], job["type"], job.get("params", {})
        started = datetime.now(timezone.utc)
        async with self.job_slots:
            try:
                if jtype == "iperf3":
                    async with self.iperf_lock:
                        payload = await execute(jtype, params)
                else:
                    payload = await execute(jtype, params)
            except JobError as e:
                payload = {"status": "failed", "error": str(e)}
            except Exception as e:  # noqa: BLE001
                log.exception("job %s crashed", job_id)
                payload = {"status": "failed", "error": f"agent error: {e.__class__.__name__}: {e}"}
        payload["started_at"] = started.isoformat()
        payload["finished_at"] = datetime.now(timezone.utc).isoformat()
        log.info("job %s (%s) %s", job_id, jtype, payload["status"])
        for attempt in range(5):
            try:
                await self._request("POST", f"/jobs/{job_id}/result", json=payload)
                return
            except FatalAuthError:
                raise
            except (httpx.HTTPError, OSError) as e:
                log.warning("reporting job %s failed: %s", job_id, e)
                await self._sleep(2 ** attempt)

    async def poll_jobs(self) -> None:
        backoff = 1.0
        while not self.stop.is_set():
            try:
                r = await self._request(
                    "GET", "/jobs", params={"wait": 20}, timeout=httpx.Timeout(40.0, connect=10.0)
                )
                backoff = 1.0
                for job in r.json():
                    t = asyncio.create_task(self._run_job(job))
                    self.tasks.add(t)
                    t.add_done_callback(self.tasks.discard)
            except FatalAuthError:
                raise
            except (httpx.HTTPError, OSError, ValueError) as e:
                log.warning("job poll failed: %s (retry in %.0fs)", e, backoff)
                await self._sleep(backoff + random.random())
                backoff = min(backoff * 2, 60.0)

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.stop.set)
        log.info("ipf3-agent %s starting; server %s", __version__, self.cfg.server_url)
        await self.send_heartbeat()
        runners = [
            asyncio.create_task(self._periodic("metrics", self.cfg.metrics_interval, self.send_metrics)),
            asyncio.create_task(self._periodic("inventory", self.cfg.inventory_interval, self.send_inventory)),
            asyncio.create_task(self._periodic("heartbeat", self.cfg.heartbeat_interval, self.send_heartbeat)),
            asyncio.create_task(self.poll_jobs()),
        ]
        stopper = asyncio.create_task(self.stop.wait())
        done, _ = await asyncio.wait([*runners, stopper], return_when=asyncio.FIRST_COMPLETED)
        self.stop.set()
        for t in runners:
            t.cancel()
        for t in list(self.tasks):
            t.cancel()
        await asyncio.gather(*runners, *self.tasks, return_exceptions=True)
        await self.client.aclose()
        for t in done:
            if t is not stopper and t.exception():
                raise t.exception()
        log.info("ipf3-agent stopped")
