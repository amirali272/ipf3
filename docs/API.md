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

## VPN API (`/api/v1/vpn`) — for sales / management bots

This is what a Telegram (or other) bot uses to sell and manage VPN accounts: create a
user, read their usage and links, renew, disable, delete. Same auth as above — bearer
token, no separate API-key scheme.

**Bot credential.** Create a dedicated account with the `operator` role for the bot
(`ipf3-server create-user vpnbot --role operator`); operator can manage VPN users but
not panel admins, nodes or server settings. Log in once to get a session JWT and use
it as a long-lived bearer token — `session_ttl_minutes` (default 720 = 12h) controls
how long it lasts, so either re-login when a request gets 401, or raise
`IPF3_SESSION_TTL_MINUTES` for a bot account. Treat the token like a password: keep it
server-side only.

Role in brackets: V = viewer, O = operator, A = admin.

| Method & path | Role | Description |
|---|---|---|
| `GET /vpn/users?search&status` | V | List users (`status` ∈ `active,expired,limited,disabled,online`) |
| `POST /vpn/users` | O | Create — `{username, data_limit_gb, expire_days, inbound_ids, note}`. `inbound_ids: null` = all inbounds |
| `GET /vpn/users/{id}` | V | One user |
| `PATCH /vpn/users/{id}` | O | Partial update — same fields, plus `clear_expire`, `all_inbounds` |
| `DELETE /vpn/users/{id}` | O | Delete |
| `POST /vpn/users/{id}/reset-traffic` | O | Zero `used_up`/`used_down` |
| `POST /vpn/users/{id}/revoke` | O | New `uuid`/`password`/`sub_token` — invalidates old configs and the old sub link |
| `GET /vpn/users/{id}/links` | V | `{links: [share links...]}` for every enabled inbound the user can use |
| `GET /vpn/users/{id}/usage?days` | V | Daily up/down bytes |
| `GET /vpn/users/{id}/activity` | V | Connected IPs right now (per node) and client apps that fetched the subscription |
| `GET /vpn/overview` | V | Fleet totals: users by status, traffic, top users |
| `GET /vpn/nodes` | V | Nodes with Xray state (`online`, `running`, `in_sync`, `inbounds`, `online_users`) |
| `GET /vpn/inbounds` | V | Inbounds with per-inbound traffic and online count |
| `POST/PUT/DELETE /vpn/inbounds[/{id}]` | A | Inbound CRUD (needed once per node/protocol, not per sale) |
| `GET/POST/PUT/DELETE /vpn/outbounds[/{id}]` | A | Outbounds from a share link or JSON (see [docs/VPN.md](VPN.md)) |
| `GET/POST/PUT/DELETE /vpn/routing[/{id}]` · `POST /vpn/routing/order` | A | Routing rules |

A created or fetched user's `VpnUserOut` has everything a bot message needs directly:
`status`, `data_limit`/`used`/`used_up`/`used_down` (bytes), `expire_at`, `enabled`,
`online`, `online_ips`, `sub_url` (the one link to hand the customer — it serves base64,
clash YAML or a browser status page depending on the client). You don't need
`/vpn/users/{id}/links` unless you want to send raw per-protocol configs instead of the
subscription link.

### Example: sell a plan (Telegram bot flow)

```bash
TOKEN=...   # bearer token for the vpnbot account, obtained once via /api/v1/auth/login

# 1) create a 30-day, 50 GB account named after the Telegram user id
curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"username":"tg_123456789","data_limit_gb":50,"expire_days":30,"note":"tg:123456789"}' \
  https://ipf3.example.com/api/v1/vpn/users | jq '{id, sub_url, expire_at}'

# 2) later: check remaining usage before renewal
curl -s -H "Authorization: Bearer $TOKEN" \
  https://ipf3.example.com/api/v1/vpn/users/<id> | jq '{status, used, data_limit, expire_at}'

# 3) renew: add 30 more days and reset the data counter
curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -X PATCH -d '{"expire_days":30}' https://ipf3.example.com/api/v1/vpn/users/<id>
curl -s -H "Authorization: Bearer $TOKEN" -X POST \
  https://ipf3.example.com/api/v1/vpn/users/<id>/reset-traffic

# 4) non-payment: disable (keeps history) rather than delete
curl -s -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -X PATCH -d '{"enabled":false}' https://ipf3.example.com/api/v1/vpn/users/<id>
```

`username` must match `^[A-Za-z0-9_.-]{2,64}$` and be unique; a 409 means it's taken —
append the Telegram id or similar instead of retrying with the same name.
`data_limit_gb: 0` and omitting `expire_days` both mean unlimited/no-expiry.

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
