# Architecture

## Components

**ipf3-server: API** (`server/ipf3_server`)
- FastAPI app with async SQLAlchemy 2 on asyncpg.
- Stateless, so you can run several uvicorn workers.
- Routers:
  - `auth`, `users`: sessions and RBAC.
  - `agents`: inventory, telemetry queries and enrollment tokens.
  - `jobs`: tests and schedules.
  - `alerts`, `analytics`, `audit`.
  - `live`: WebSocket.
  - `agent_api`: the agent protocol.

**ipf3-server: worker** (`worker.py`)
- A single active instance, guarded by `pg_try_advisory_lock`. It runs three loops:
  - **scheduler** (5 s): creates jobs for due schedules. It skips a schedule whose
    previous run is still queued or running, then expires stale queued and running jobs.
  - **alerts** (30 s): `services/alerting.evaluate` computes each rule's value per
    agent, opens or resolves `alert_events`, then sends webhooks and email.
  - **retention** (1 h): deletes rows past their retention period.

**ipf3-agent** (`agent/ipf3_agent`)
- One asyncio process with four loops: metrics, inventory, heartbeat, and job long-poll.
- `collect.py` reads kernel counters through psutil, plus `/proc/net/{tcp,tcp6,udp,udp6,snmp}`,
  `ip -j addr/route`, `ss -H -tuna` and resolv.conf.
- `tools.py` builds argv for iperf3, ping, traceroute and mtr, and runs DNS queries
  with dnspython.

**web** (`web/src`)
- React 18, TanStack Query, React Router, Tailwind and Recharts.
- `lib/live.ts` subscribes to the WebSocket. Pages under `pages/` cover Dashboard,
  Servers, Server detail, Speed & Diagnostics, Job detail, Schedules, Analytics, Alerts,
  Users, Audit and Account.

## Data flow

```
agent ──POST /metrics (10 s)──► metric_samples + interface_samples ──► /agents/{id}/metrics (date_bin)
      ──POST /inventory (60 s)─► agent_inventory (upsert JSONB)     ──► /agents/{id}/inventory
      ◄─GET /jobs (long poll)── jobs (queued→running, SKIP LOCKED)  ◄── POST /jobs (operator) / worker (schedules)
      ──POST /jobs/{id}/result► parsers.py ─► jobs.result + bps/rtt/loss/jitter/retransmits
                                                                    ──► /analytics/tests, alert rules
```

## Why the server parses raw output

Agents report the exact stdout of each tool. The server parses it in
`services/parsers.py`, which has these benefits:

- Agents stay small, auditable executors with no business logic.
- The stored raw output is the evidence behind every number. Parsers can be improved
  and re-run without touching agents.
- One tested parser suite covers every agent version.

## Schema

| Table | Purpose |
|---|---|
| `users` | Accounts, argon2id hashes, lockout state, `session_version` |
| `agents` | Identity, system info, detected tools, credential hash, last contact |
| `enrollment_tokens` | Hashed one-time tokens |
| `metric_samples` | Per-agent system sample every interval. Indexed on `(agent_id, ts)`. |
| `interface_samples` | Per-interface rates and error/drop deltas. Indexed on `(agent_id, iface, ts)`. |
| `agent_inventory` | Latest inventory snapshot (JSONB) |
| `jobs` | Tests: params, status, raw output, parsed result, summary columns |
| `schedules` | Recurring job definitions |
| `alert_rules`, `alert_events` | Rules and their firing/resolved history |
| `audit_log` | Security-relevant actions |

Migrations live in `server/ipf3_server/migrations` (Alembic). Run them with
`ipf3-server migrate`.

## Measurement semantics

| Measurement | How it's computed |
|---|---|
| Interface rate | (counter[t] − counter[t−1]) × 8 / Δt, using a monotonic clock. A counter reset (value decreases) yields 0 for that interval instead of a bogus spike. |
| Host rx/tx | Sum over the interfaces that aren't excluded. `lo` is excluded by default. |
| Ping jitter | Mean absolute difference between consecutive RTTs, in sequence order. Duplicate replies are ignored. |
| iperf3 throughput | Receiver-side `sum_received` for TCP. For UDP, receiver stats are preferred when present (newer iperf3), otherwise `sum`. Omitted intervals are excluded from charts. |
| MTR jitter column | StDev of the last hop's RTT. |
| Historical buckets | `date_bin()` aligned to the Unix epoch. About 300 points per chart by default, with nice bucket sizes from 10 s to 1 d. |
