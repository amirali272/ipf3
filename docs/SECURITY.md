# Security model

## Assets and trust boundaries

| Boundary | Protection |
|---|---|
| Browser ↔ server | TLS 1.2/1.3 via nginx with HSTS. Session cookie is `HttpOnly; Secure; SameSite=Strict`. Double-submit CSRF token on every mutating request. Strict CSP (`script-src 'self'`) and `frame-ancestors 'none'`. |
| Agent ↔ server | TLS with certificate verification (system store or a pinned `ca_file`). Per-agent bearer credential `<agent_id>.<256-bit secret>`. Only the SHA-256 of the secret is stored, and it's compared in constant time. Agents connect outbound only. |
| Server ↔ PostgreSQL | Local Unix socket with peer authentication. The role is a non-superuser that owns only the `ipf3` database. `PUBLIC` privileges are revoked. |
| Server → measured hosts | None. The server never connects to agents. |

## Authentication and authorization

- **Passwords** use argon2id (argon2-cffi defaults) and are rehashed transparently when
  parameters change. The policy is at least 12 characters with at least 3 character
  classes.
- **Brute force** is limited per account (5 failures → 15 min lockout, configurable),
  per IP (10 attempts/min in-process), and by an nginx `limit_req` on `/api/v1/auth/login`
  and `/api/agent/v1/enroll`. Unknown usernames still run a password verification, so
  timing doesn't reveal which accounts exist.
- **Sessions** are HS256 JWTs. Each one carries a per-user `session_version`, which is
  incremented on password change, role change, deactivation or admin reset. That
  invalidates every existing session immediately.
- **RBAC** is enforced server-side on every endpoint:

  | Capability | viewer | operator | admin |
  |---|:-:|:-:|:-:|
  | View dashboards, telemetry, inventory, results, alerts | ✓ | ✓ | ✓ |
  | Run and cancel tests, manage schedules, acknowledge alerts | | ✓ | ✓ |
  | Enroll, rename, disable or delete servers, rotate agent credentials | | | ✓ |
  | Manage alert rules (they hold webhook URLs and emails) | | | ✓ |
  | Manage users, read the audit log | | | ✓ |

  The last active admin can't be demoted, deactivated or deleted.
- **Agent enrollment** uses tokens that are random (256-bit), single-use, expiring,
  revocable, stored hashed, and shown exactly once. Each enrollment is consumed under a
  row lock, so a token can't be raced into two agents.
- **Agent credentials** can be rotated (the old credential stops working immediately) or
  revoked by disabling or deleting the server. An agent whose credential is rejected
  exits with code 78, and systemd won't restart-loop it.

## Command execution on agents (least privilege)

The server can only queue jobs of **five fixed types**. Each type has a strict parameter
schema (`extra="forbid"`, bounded integers, enumerated protocols). Targets must be IP
literals or RFC 1123 hostnames, so leading `-` and shell metacharacters are rejected.

The agent **re-validates** every parameter independently. It builds argv lists (no
shell), runs them with a fixed `PATH`, closed stdin, a timeout and capped output. There
is no "custom arguments" field anywhere. A compromised control plane can make an agent
send pings or iperf3 traffic to chosen hosts within those bounds, but it can't execute
arbitrary commands.

The `ipf3-agent` systemd unit runs as a dedicated system user and keeps
**`CAP_NET_RAW` only**, which raw-socket probes need (traceroute `-I`/`-T`, MTR). It
also sets:

```
NoNewPrivileges=yes  ProtectSystem=strict  ReadOnlyPaths=/  ProtectHome=yes  PrivateTmp=yes
PrivateDevices=yes  ProtectKernel*=yes  RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
SystemCallFilter=@system-service  MemoryMax=512M  TasksMax=128
InaccessiblePaths=/root /etc/ssh /etc/shadow …
```

Telemetry comes from world-readable `/proc/net/*`, psutil, `ip -j` (netlink), and `ss`
**without** `-p`. None of these need root.

The optional `ipf3-iperf3` endpoint runs under `DynamicUser=yes` with an empty
capability bounding set, `MemoryDenyWriteExecute`, and only `AF_INET`/`AF_INET6`.

The API and worker run as user `ipf3` with no capabilities, `ProtectSystem=strict`,
`PrivateUsers`, `ProtectProc=invisible` and `SystemCallFilter=@system-service`. They
have read-only access to `/opt/ipf3` and `/etc/ipf3`.

## Data handling

- Raw tool output is stored next to parsed results, for audit and re-parsing. It's
  bounded to 2 MB per job.
- The audit log records logins (successful, failed, locked), user and agent changes,
  enrollment, token creation and deletion, credential rotation, job creation and
  cancellation, schedule changes, alert rule changes and acknowledgements. Each entry has
  a timestamp, actor and client IP.
- Retention purges old metrics, results, events and audit entries (see
  [CONFIGURATION.md](CONFIGURATION.md)).

## Hardening checklist

- [ ] Use a publicly trusted certificate, or distribute your CA to agents with `--ca-file`.
- [ ] Restrict 443 to operator and agent networks if the UI doesn't need to be public.
- [ ] Firewall iperf3 endpoints (TCP and UDP) to the hosts that test against them.
- [ ] Change the initial admin password. Create named accounts with the least role needed.
- [ ] Configure SMTP or webhooks so alerts reach people.
- [ ] Copy `/var/backups/ipf3` off-host (backups include `server.env`, which holds the
      secret key).
- [ ] Keep Ubuntu updated (`unattended-upgrades`). Upgrade IPF3 with `deploy/upgrade-server.sh`.
- [ ] Webhook URLs are admin-controlled outbound requests from the worker. Restrict
      egress from the server if your policy requires it.

## Reporting vulnerabilities

Please open a private security advisory on the GitHub repository instead of a public
issue.
