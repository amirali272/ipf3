#!/usr/bin/env bash
# Install or update the IPF3 server code, Python environment and web UI from this
# checkout into /opt/ipf3, then apply database migrations. Used by
# install-server.sh and upgrade-server.sh.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SKIP_RESTART=0
SKIP_WEB_BUILD=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-restart) SKIP_RESTART=1; shift ;;
    --skip-web-build) SKIP_WEB_BUILD=1; shift ;;
    *) die "unknown option: $1" ;;
  esac
done
require_root

REPO="$(repo_root)"
PREFIX=/opt/ipf3
if [[ $SKIP_WEB_BUILD -eq 0 ]] && prebuilt_web_ok "$REPO"; then
  SKIP_WEB_BUILD=1
fi

info "Python environment"
if [[ ! -x "$PREFIX/venv/bin/python" ]]; then
  python3 -m venv "$PREFIX/venv"
fi
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q -r "$REPO/server/requirements.lock"
"$PREFIX/venv/bin/pip" install -q --no-deps --force-reinstall "$REPO/server"

info "Web UI"
if [[ $SKIP_WEB_BUILD -eq 1 ]]; then
  info "Using the prebuilt web UI"
  [[ -f "$REPO/web/dist/index.html" ]] || die "web/dist not found; build it first (cd web && npm ci && npm run build)"
  DIST="$REPO/web/dist"
else
  # Build unprivileged in a scratch copy: npm lifecycle scripts never run as root.
  BUILD=$(mktemp -d /tmp/ipf3-web.XXXXXX)
  trap 'rm -rf "$BUILD"' EXIT
  rsync -a --exclude node_modules --exclude dist "$REPO/web/" "$BUILD/"
  chown -R ipf3:ipf3 "$BUILD"
  command -v npm >/dev/null || die "web/dist does not match the sources and npm is not installed; run scripts/build-web.sh on a machine with Node.js"
  info "Building the web UI with npm (this can take a few minutes)"
  runuser -u ipf3 -- env HOME="$BUILD" npm_config_cache="$BUILD/.npm" bash -c "cd '$BUILD' && npm ci --no-audit --no-fund && npm run build"
  DIST="$BUILD/dist"
fi
install -d -m 0755 "$PREFIX/web"
rsync -a --delete --exclude BUILD_ID "$DIST/" "$PREFIX/web/"
chown -R root:root "$PREFIX/web"
find "$PREFIX/web" -type d -exec chmod 0755 {} + -o -type f -exec chmod 0644 {} +

info "Operational scripts"
install -d -m 0755 "$PREFIX/deploy"
install -m 0755 "$REPO/deploy/lib.sh" "$REPO/deploy/backup.sh" "$REPO/deploy/restore.sh" "$PREFIX/deploy/"
cp "$REPO/VERSION" "$PREFIX/VERSION"

ensure_etc_dir
[[ -f /etc/ipf3/server.env ]] && chown root:ipf3 /etc/ipf3/server.env && chmod 0640 /etc/ipf3/server.env

# Daily/monthly traffic totals follow the server's local calendar.
if [[ -f /etc/ipf3/server.env ]] && ! grep -q '^IPF3_USAGE_TIMEZONE=' /etc/ipf3/server.env; then
  TZ_NAME=$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)
  printf 'IPF3_USAGE_TIMEZONE=%s\n' "${TZ_NAME:-UTC}" >> /etc/ipf3/server.env
fi

info "Database migrations"
ipf3_cli migrate

if [[ $SKIP_RESTART -eq 0 ]]; then
  info "Restarting services"
  systemctl restart ipf3-api.service ipf3-worker.service
  for _ in $(seq 1 30); do
    curl -fsS http://127.0.0.1:8000/readyz >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS http://127.0.0.1:8000/readyz >/dev/null || die "API not ready after restart; see: journalctl -u ipf3-api"
fi
info "Installed version $(cat "$PREFIX/VERSION")"
