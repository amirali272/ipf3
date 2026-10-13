# Developer shortcuts. Production installs use deploy/*.sh.
PY ?= python3
VENV ?= .venv
DB ?= postgresql+asyncpg://ipf3:ipf3@127.0.0.1:5432/ipf3

.PHONY: venv dev-db migrate api worker web test test-server test-agent test-web lint

venv:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/pip install -r server/requirements.lock -r agent/requirements.lock
	$(VENV)/bin/pip install --no-deps -e server -e agent
	$(VENV)/bin/pip install pytest pytest-asyncio

dev-db:
	docker compose -f docker-compose.dev.yml up -d postgres

migrate:
	IPF3_DATABASE_URL=$(DB) $(VENV)/bin/ipf3-server migrate

api:
	IPF3_DATABASE_URL=$(DB) IPF3_COOKIE_SECURE=false $(VENV)/bin/ipf3-server serve --port 8000 --workers 1

worker:
	IPF3_DATABASE_URL=$(DB) $(VENV)/bin/ipf3-server worker

web:
	cd web && npm ci && npm run dev

test: test-server test-agent test-web

test-server:
	cd server && IPF3_TEST_DATABASE_URL=$${IPF3_TEST_DATABASE_URL:-postgresql+asyncpg://ipf3:ipf3@127.0.0.1:5432/ipf3_test} ../$(VENV)/bin/pytest -q

test-agent:
	cd agent && ../$(VENV)/bin/pytest -q

test-web:
	cd web && npm run typecheck && npm test

lint:
	shellcheck -x -S warning install.sh deploy/*.sh
