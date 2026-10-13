# Configuration reference

## Server: `/etc/ipf3/server.env`

The server reads settings from environment variables prefixed with `IPF3_`. systemd loads
them from `/etc/ipf3/server.env`, which is `root:ipf3 0640`. After editing the file,
restart the services: `systemctl restart ipf3-api ipf3-worker`.

| Variable | Default | Description |
|---|---|---|
| `IPF3_DATABASE_URL` | `postgresql+asyncpg://ipf3:ipf3@127.0.0.1:5432/ipf3` | SQLAlchemy async URL. The installer uses `postgresql+asyncpg://ipf3@/ipf3?host=/var/run/postgresql`, which is Unix-socket peer auth with no password. |
| `IPF3_SECRET_KEY` | — (**required**, ≥ 32 chars) | HMAC key for session tokens. Rotating it signs every user out. Agent credentials are unaffected. |
| `IPF3_SESSION_TTL_MINUTES` | `720` | Session lifetime. |
| `IPF3_COOKIE_SECURE` | `true` | Sets the `Secure` flag on cookies. Set it to `false` only for local plain-HTTP development. |
| `IPF3_CORS_ORIGINS` | *(empty)* | Comma-separated extra origins. Not needed when the UI is served from the same origin. |
| `IPF3_TRUSTED_PROXIES` | `127.0.0.1,::1` | Peers whose `X-Forwarded-For` header is trusted when deriving client IPs (audit log and rate limits). |
| `IPF3_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Passed to uvicorn `forwarded_allow_ips`. |
| `IPF3_AGENT_OFFLINE_SECONDS` | `90` | An agent with no contact for longer than this is shown as offline. |
| `IPF3_JOB_QUEUED_TIMEOUT_SECONDS` | `600` | A queued job that no agent picks up within this time is marked `expired`. |
| `IPF3_JOB_RUNNING_TIMEOUT_SECONDS` | `900` | A running job with no reported result within this time is marked `expired`. |
| `IPF3_ENROLLMENT_TOKEN_TTL_HOURS` | `24` | Default lifetime of enrollment tokens. |
| `IPF3_MAX_PAYLOAD_BYTES` | `4194304` | Maximum request body size. nginx also enforces 4 MB. |
| `IPF3_RETENTION_METRICS_DAYS` | `30` | System and interface samples. |
| `IPF3_RETENTION_JOBS_DAYS` | `180` | Test results, including raw output. |
| `IPF3_RETENTION_ALERTS_DAYS` | `365` | Resolved alert events. |
| `IPF3_RETENTION_AUDIT_DAYS` | `365` | Audit log. |
| `IPF3_LOGIN_MAX_FAILURES` | `5` | Failed logins allowed before the account is locked. |
| `IPF3_LOGIN_LOCKOUT_MINUTES` | `15` | Lockout duration. |
| `IPF3_SCHEDULER_INTERVAL` | `5` | How often (in seconds) the worker checks schedules and job expiry. |
| `IPF3_ALERT_INTERVAL` | `30` | How often (in seconds) alert rules are evaluated. |
| `IPF3_RETENTION_INTERVAL` | `3600` | How often (in seconds) retention purges run. |
| `IPF3_SMTP_HOST` | *(empty)* | Email notifications are enabled when this is set. |
| `IPF3_SMTP_PORT` | `587` | |
| `IPF3_SMTP_USER` / `IPF3_SMTP_PASSWORD` | | Optional SMTP authentication. |
| `IPF3_SMTP_FROM` | `ipf3@localhost` | |
| `IPF3_SMTP_STARTTLS` | `true` | Uses STARTTLS with certificate verification. |
| `IPF3_WEBHOOK_TIMEOUT_SECONDS` | `10` | |
| `IPF3_WEB_ROOT` | *(empty)* | Lets FastAPI serve the built UI itself. Use it only when nginx isn't in front. |

To change the number of API worker processes, edit
`/etc/systemd/system/ipf3-api.service.d/workers.conf` (`Environment=IPF3_WORKERS=4`) and
run `systemctl daemon-reload && systemctl restart ipf3-api`.

## Agent: `/etc/ipf3/agent.json`

The agent's enrollment writes this file. It's `root:ipf3-agent 0640`. After editing it,
restart the agent: `systemctl restart ipf3-agent`.

```json
{
  "server_url": "https://ipf3.example.com",
  "agent_id": "c52da338-32f5-405e-928f-9559272c12ff",
  "agent_token": "c52da338-….<secret>",
  "name": "fra1-edge-03",
  "ca_file": null,
  "metrics_interval": 10.0,
  "inventory_interval": 60.0,
  "heartbeat_interval": 60.0,
  "max_concurrent_jobs": 2,
  "max_connections_reported": 2000,
  "exclude_interfaces": ["lo"]
}
```

| Key | Description |
|---|---|
| `server_url` | Must be `https://`. Plain HTTP is refused unless `IPF3_AGENT_ALLOW_HTTP=1` is set, which is meant for development only. |
| `ca_file` | PEM bundle used to verify a private or self-signed server certificate. Without it, the system trust store is used. |
| `metrics_interval` | Seconds between samples. Rates are computed from kernel counter deltas over this interval. |
| `inventory_interval` | Seconds between refreshes of interfaces, routes, sockets and DNS configuration. |
| `max_concurrent_jobs` | Number of diagnostic jobs that can run in parallel. iperf3 jobs always run one at a time, so they don't skew each other's results. |
| `max_connections_reported` | Upper bound on the number of sockets uploaded per inventory refresh. |
| `exclude_interfaces` | Interfaces left out of rate collection. |

## Alert metrics

| Metric | Evaluation |
|---|---|
| `cpu_percent`, `mem_percent`, `disk_percent`, `load1` | Must hold for **every** sample in the `for_seconds` window: `min` is compared for `>`/`>=`, `max` for `<`/`<=`. |
| `iface_rx_bps`, `iface_tx_bps` | Same sustained semantics, for one interface or the host total. |
| `iface_errors` | Sum of errors and drops in the window. |
| `agent_offline` | Seconds since the agent last made contact. |
| `ping_loss_percent`, `ping_rtt_ms`, `ping_jitter_ms`, `iperf3_bps`, `iperf3_loss_percent`, `dns_time_ms` | Average over completed tests in `max(for_seconds, 900 s)`. Can be restricted to one test target. |
| `job_failed` | Number of failed or expired **scheduled** tests in `max(for_seconds, 900 s)`. |

An event opens when the condition becomes true for a server. It resolves when the
condition is false and data is present. Notifications are sent on both transitions.
