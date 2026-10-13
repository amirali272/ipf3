# Development

## Prerequisites

You need Python ≥ 3.10, Node.js ≥ 18, and PostgreSQL ≥ 14. The easiest way to get
PostgreSQL is `docker compose -f docker-compose.dev.yml up -d postgres`. For realistic
agent tests, install `iperf3`, `iputils-ping`, `traceroute`, `mtr-tiny` and `iproute2`.

## Setup

```bash
make venv            # .venv with server + agent (editable) and test deps
make dev-db          # PostgreSQL 16 on 127.0.0.1:5432 (ipf3/ipf3), plus ipf3_test
export IPF3_SECRET_KEY=$(openssl rand -hex 32)
make migrate
echo 'Dev-Admin-Passw0rd!' | IPF3_DATABASE_URL=postgresql+asyncpg://ipf3:ipf3@127.0.0.1:5432/ipf3 .venv/bin/ipf3-server create-user admin
make api             # terminal 1: http://127.0.0.1:8000 (/api/docs)
make worker          # terminal 2
make web             # terminal 3: http://127.0.0.1:5173 (proxies /api to :8000)
```

To run a local agent against the dev server:

```bash
iperf3 -s -B 127.0.0.1 &                                  # local test endpoint
TOKEN=…   # create one in the UI: Servers → Enroll server
IPF3_AGENT_ALLOW_HTTP=1 .venv/bin/ipf3-agent --config ./agent.dev.json enroll \
  --server http://127.0.0.1:8000 --token "$TOKEN" --name dev
IPF3_AGENT_ALLOW_HTTP=1 .venv/bin/ipf3-agent --config ./agent.dev.json run
```

`IPF3_AGENT_ALLOW_HTTP` exists for local development only. Production agents refuse
plain HTTP.

## Tests

```bash
make test-server     # 60 tests: API, RBAC, CSRF, lockout, agent protocol, jobs, schedules, alerts, parsers,
                     #   retention, and real agent ↔ API integration (real ping/iperf3 when installed)
make test-agent      # 45 tests: argv building & injection rejection, /proc parsing, ss/resolv parsing, config
make test-web        # typecheck + vitest
make lint            # shellcheck deploy scripts
```

Server tests need a disposable database. The suite drops and recreates the `public`
schema of `IPF3_TEST_DATABASE_URL`, then runs the real Alembic migrations, so migrations
are tested too.

Parser fixtures in `server/tests/fixtures` follow the real output formats of iperf3
3.16 (`-J`), iputils ping, traceroute 2.1 and mtr 0.95 (`--json`).

## Database migrations

After changing `models.py`:

```bash
cd server
IPF3_DATABASE_URL=… alembic -c ipf3_server/alembic.ini revision --autogenerate -m "describe change" --rev-id 0002
```

Review the generated file. Autogenerate doesn't create or drop PostgreSQL enum values.

## Dependency pins

`server/requirements.lock` and `agent/requirements.lock` are resolved for Python 3.10
(Ubuntu 22.04). The same wheels are verified to exist for 3.12 and 3.13. When you
update them, re-resolve with `pip download --python-version 3.10 --only-binary=:all:`,
then run the test suites on 3.10 and 3.12 (CI does both).
