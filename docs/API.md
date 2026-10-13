# HTTP API

Interactive OpenAPI documentation is served at **`/api/docs`**, and the schema at
`/api/openapi.json`. All timestamps are ISO 8601 in UTC. Bit rates are bit/s and times
are milliseconds unless the field name says otherwise.

## Authentication

- **Browser**: `POST /api/v1/auth/login` sets `ipf3_session` (HttpOnly) and `ipf3_csrf`.
  Every non-GET request must send the `ipf3_csrf` cookie value in the `X-IPF3-CSRF`
  header.
- **Scripts**: send `Authorization: Bearer <session JWT>`. You can obtain the JWT by
  logging in and reading the `ipf3_session` cookie. CSRF checks don't apply to bearer
  authentication.

```bash
curl -c jar -H 'content-type: application/json' \
     -d '{"username":"admin","password":"…"}' https://ipf3.example.com/api/v1/auth/login
TOKEN=$(awk '$6=="ipf3_session"{print $7}' jar)
curl -H "Authorization: Bearer $TOKEN" https://ipf3.example.com/api/v1/agents
```

## User API (`/api/v1`)

Role in brackets: V = viewer, O = operator, A = admin.

| Method & path | Role | Description |
|---|---|---|
| `POST /auth/login` · `POST /auth/logout` · `GET /auth/me` · `POST /auth/change-password` | — / V | Session management |
| `GET/POST /users`, `PATCH/DELETE /users/{id}` | A | User admin (`role`, `is_active`, `password`, `unlock`) |
| `GET /agents` | V | Servers with `online` and the `latest` sample |
| `GET /agents/{id}` · `PATCH /agents/{id}` · `DELETE /agents/{id}` | V / A / A | Detail, rename, tags, disable, delete |
| `POST /agents/{id}/rotate-token` | A | New agent credential (returned once) |
| `GET /agents/{id}/metrics?from&to&bucket` | V | Bucketed system series (avg; max for rates) |
| `GET /agents/{id}/interfaces/metrics?iface&from&to&bucket` | V | Bucketed per-interface series |
| `GET /agents/{id}/inventory` | V | Interfaces, routes (v4 and v6), sockets, DNS, system |
| `GET/POST /enrollment-tokens`, `DELETE /enrollment-tokens/{id}` | A | One-time enrollment tokens (plaintext returned only on creation) |
| `POST /jobs` | O | `{agent_id, type, params}`; `type` ∈ `iperf3, ping, traceroute, mtr, dns` |
| `GET /jobs?agent_id&type&status&schedule_id&target&before&limit` | V | Job list with summary columns |
| `GET /jobs/{id}` · `POST /jobs/{id}/cancel` | V / O | Parsed `result` and `raw` output; cancel |
| `GET/POST /schedules`, `PATCH/DELETE /schedules/{id}` | V / O | Recurring tests (≥ 30 s; iperf3 ≥ 300 s) |
| `GET /alerts/metrics` | V | Available alert metrics |
| `GET/POST /alerts/rules`, `PATCH/DELETE /alerts/rules/{id}` | V / A | Alert rules |
| `GET /alerts/events?state&agent_id&limit` · `POST /alerts/events/{id}/ack` | V / O | Events and acknowledgement |
| `GET /analytics/overview` | V | Fleet counters |
| `GET /analytics/tests?type&agent_id&target&from&to&bucket` | V | Test series and summary (avg, p95 RTT, loss, jitter) |
| `GET /analytics/targets?days` | V | Distinct (agent, type, target) combinations |
| `GET /analytics/fleet?from&to` | V | Per-server utilisation over a period |
| `GET /analytics/usage?days&agent_id&iface` | V | Bytes consumed today, this month, and per day (`iface=*` = host total over physical NICs) |
| `GET /analytics/live` | V | Latest ≈2 s current-rate report per agent |
| `GET /analytics/fleet-bandwidth?from&to&bucket` | V | Fleet rx/tx series (per-agent average, then summed across agents) |
| `GET /system/status` | V | Control-plane health (API, database, worker) and host CPU, memory and disk |
| `GET /audit?action&username&before_id&limit` | A | Audit log (keyset pagination) |
| `WS /ws/live` | V (cookie) | Live frames every 2 s. Send `{"focus": "<agent_id>"}` to also receive that agent's interface samples. |

### Job parameters

| Type | Parameters (defaults) |
|---|---|
| `iperf3` | `target`, `port` (5201), `protocol` (`tcp`/`udp`), `duration` (10, max 300), `parallel` (1–32), `reverse`, `bidir`, `bitrate_bps`, `omit` (0–10), `ipv6` |
| `ping` | `target`, `count` (20, max 1000), `interval` (1.0, min 0.2), `packet_size` (56), `ipv6` |
| `traceroute` | `target`, `max_hops` (30), `queries` (3), `protocol` (`udp`/`icmp`/`tcp`), `ipv6` |
| `mtr` | `target`, `count` (10), `max_hops` (30), `protocol` (`icmp`/`udp`/`tcp`), `ipv6` |
| `dns` | `name`, `record_type` (`A`…`CAA`; an IP address means a PTR lookup), `server` (IP or system default), `protocol` (`udp`/`tcp`), `timeout` (5) |

Unknown keys are rejected with HTTP 422.

### Example: run a UDP speed test and wait for the result

```bash
JOB=$(curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"agent_id":"<id>","type":"iperf3","params":{"target":"10.0.0.3","protocol":"udp","bitrate_bps":500000000,"duration":10}}' \
  https://ipf3.example.com/api/v1/jobs | jq -r .id)
until curl -s -H "Authorization: Bearer $TOKEN" https://ipf3.example.com/api/v1/jobs/$JOB \
      | jq -e '.status|IN("completed","failed","expired","cancelled")' >/dev/null; do sleep 2; done
curl -s -H "Authorization: Bearer $TOKEN" https://ipf3.example.com/api/v1/jobs/$JOB | jq '{status, bps, jitter_ms, loss_percent}'
```

## Agent protocol (`/api/agent/v1`)

Every request except enrollment carries `Authorization: Bearer <agent_id>.<secret>`.

| Method & path | Body | Notes |
|---|---|---|
| `POST /enroll` | `{enrollment_token, name, system}` | Returns `{agent_id, agent_token}` (201). The token is consumed. |
| `POST /heartbeat` | `{system: {hostname, os_name, kernel, agent_version, cpu_count, capabilities}}` | Every 60 s; updates detected tools |
| `POST /metrics` | `{ts, system: {...}, interfaces: [{iface, rx_bps, tx_bps, rx_pps, tx_pps, rx_errs, tx_errs, rx_drops, tx_drops, rx_bytes, tx_bytes, primary}]}` | Every 10 s. Rates come from counter deltas. Timestamps skewed by more than 10 min are replaced with the receipt time. |
| `POST /live` | `{interfaces: [{iface, rx_bps, tx_bps, primary}]}` | Every ≈2 s. Overwrites a single row per agent; not stored as history. |
| `POST /inventory` | `{interfaces, routes, routes6, connections, dns, system}` | Every 60 s (upsert) |
| `GET /jobs?wait=0..25&limit=1..16` | — | Long poll. Atomically claims queued jobs (`FOR UPDATE SKIP LOCKED`). |
| `POST /jobs/{id}/result` | `{status: completed\|failed, raw?, result?, error?, started_at, finished_at}` | The server parses `raw` (iperf3 JSON, ping, traceroute, mtr JSON). `result` is used for DNS only. Results for cancelled or expired jobs are ignored. |
