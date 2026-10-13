# Operations

## Services

| Unit | Host | Purpose |
|---|---|---|
| `ipf3-api.service` | control plane | FastAPI under uvicorn on `127.0.0.1:8000`, behind nginx |
| `ipf3-worker.service` | control plane | Turns schedules into jobs, expires jobs, evaluates alerts, applies retention. Holds a PostgreSQL advisory lock, so a second worker just waits. |
| `ipf3-backup.timer` | control plane | Runs `/opt/ipf3/deploy/backup.sh` daily at about 02:17 |
| `ipf3-agent.service` | every host | Telemetry and test execution |
| `ipf3-iperf3.service` | optional, per host | iperf3 test endpoint |

Logs go to the journal: `journalctl -u ipf3-api -u ipf3-worker -f` and
`journalctl -u ipf3-agent -f`.

Health endpoints are `GET /healthz` (process up) and `GET /readyz` (database reachable).

## Upgrades

### Control plane

```bash
cd ipf3 && git fetch && git checkout <new tag or main>
sudo ./deploy/upgrade-server.sh
```

The upgrade does the following, in order:

1. Takes a full backup (skip it with `--skip-backup`).
2. Refreshes the systemd units and nginx snippets.
3. Stops the worker, so no background job sees a half-migrated schema.
4. Reinstalls Python dependencies from the lock file and the application. Rebuilds the UI.
5. Runs `ipf3-server migrate` (Alembic, transactional DDL).
6. Restarts the API and worker and waits for `/readyz`.

The API is down for a few seconds during the restart. Agents buffer nothing: they retry
with exponential backoff, so you lose at most the samples from that window.

### Agents

```bash
cd ipf3 && git pull && sudo ./deploy/upgrade-agent.sh
```

Re-running `install-agent.sh` without `--token` also upgrades in place and keeps the
enrollment. The agent protocol is versioned (`/api/agent/v1`), and the server accepts
older v1 agents, so you can upgrade the control plane first and the agents gradually.

### Rolling back

```bash
sudo ./deploy/restore.sh /var/backups/ipf3/ipf3-db-<pre-upgrade>.dump --no-migrate
git checkout <previous tag>
sudo ./deploy/upgrade-server.sh --skip-backup
```

`--no-migrate` keeps the schema at the revision stored in the backup. Reinstalling the
previous version then finds nothing to migrate and starts the services.

## Backups

`backup.sh` writes the following to `/var/backups/ipf3` (mode 0700, owner `postgres`):

- `ipf3-db-<UTC>.dump`: `pg_dump` custom format, compressed. It's verified with
  `pg_restore --list` before the backup counts as successful.
- `ipf3-config-<UTC>.tar.gz`: `/etc/ipf3` (including `server.env` and its secret key)
  and the nginx site.
- `ipf3-<UTC>.sha256`: checksums of both files.

Backups older than 14 days are removed. You can change the retention and location in a
drop-in:

```bash
sudo systemctl edit ipf3-backup.service
# [Service]
# Environment=IPF3_BACKUP_KEEP_DAYS=30
# Environment=IPF3_BACKUP_DIR=/srv/backups/ipf3
```

Run a backup on demand with `sudo /opt/ipf3/deploy/backup.sh`. **Copy backups
off-host.** They contain the session signing key and every result.

## Restore

```bash
sudo ./deploy/restore.sh /var/backups/ipf3/ipf3-db-20261013T021700Z.dump \
     --config /var/backups/ipf3/ipf3-config-20261013T021700Z.tar.gz
```

The script verifies checksums, asks for confirmation, stops the services, recreates the
database, restores it, runs migrations (so an older dump is brought up to the current
schema), and restarts the services.

To restore onto a **new host**:

1. Run `install-server.sh` with the same `--domain`.
2. Run `restore.sh` with both files.
3. Point DNS at the new host.

Agents keep working without re-enrollment, because their credentials are in the
database.

## Retention and database size

The worker deletes data older than the configured retention every hour (see
[CONFIGURATION.md](CONFIGURATION.md)). PostgreSQL autovacuum reclaims the space for
reuse. To return disk space to the OS after reducing retention, run:

```bash
sudo -u postgres psql -d ipf3 -c "VACUUM (FULL, ANALYZE) metric_samples, interface_samples;"
```

`VACUUM FULL` takes exclusive locks, so run it in a maintenance window.

## Troubleshooting

| Symptom | Check |
|---|---|
| Server shows **Offline** | `systemctl status ipf3-agent`. Check `journalctl -u ipf3-agent` for TLS errors (use `--ca-file`) or HTTP 401 (credential rotated or agent deleted: re-enroll with `install-agent.sh --reenroll --server … --token …`). |
| Agent exits with status 78 | The server rejected its credential. See above. |
| Test stays **queued**, then **expired** | The agent is offline or disabled, or it was busy longer than `IPF3_JOB_QUEUED_TIMEOUT_SECONDS`. |
| iperf3 test fails with "unable to connect" | No iperf3 server is listening on the target, or a firewall blocks TCP (and UDP for UDP tests) on that port. Check `systemctl status ipf3-iperf3` on the target. |
| iperf3 "the server is busy running a test" | iperf3 servers handle one test at a time. Stagger your schedules. |
| traceroute/MTR with ICMP or TCP fails | The agent unit must keep `AmbientCapabilities=CAP_NET_RAW`. |
| "<tool> is not installed" | `apt install iperf3 iputils-ping traceroute mtr-tiny`, then `systemctl restart ipf3-agent` (capabilities are re-detected). |
| Empty charts right after enrollment | Rates need two samples. Wait one interval (10 s). |
| Locked out of the UI | `sudo -u ipf3 bash -c 'set -a; . /etc/ipf3/server.env; set +a; /opt/ipf3/venv/bin/ipf3-server create-user admin --role admin --update'` (prompts for the new password; also unlocks the account) |
| Login fails with 403 "CSRF" | The browser is blocking the `ipf3_csrf` cookie, or the UI is being served from a different origin than the API. |
| Live feed keeps reconnecting | The nginx `/api/v1/ws/live` location must pass the `Upgrade` and `Connection` headers (it does in the shipped config). The page origin must also match the `Host` header. |
