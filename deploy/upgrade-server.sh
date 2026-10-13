#!/usr/bin/env bash
# Upgrade an existing IPF3 server installation from this checkout.
#   git pull && sudo ./deploy/upgrade-server.sh [--skip-backup] [--skip-web-build]
# A backup is taken first; database migrations run automatically.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SKIP_BACKUP=0
APP_ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-backup) SKIP_BACKUP=1; shift ;;
    --skip-web-build) APP_ARGS+=(--skip-web-build); shift ;;
    *) die "unknown option: $1" ;;
  esac
done
require_root
REPO="$(repo_root)"
[[ -f /etc/ipf3/server.env ]] || die "no existing installation found (run install-server.sh)"

FROM=$(cat /opt/ipf3/VERSION 2>/dev/null || echo unknown)
TO=$(cat "$REPO/VERSION")
info "Upgrading IPF3 server $FROM -> $TO"

if [[ $SKIP_BACKUP -eq 0 ]]; then
  "$REPO/deploy/backup.sh"
fi

# Refresh unit files and nginx snippets in case they changed.
install -m 0644 "$REPO/deploy/systemd/ipf3-api.service" "$REPO/deploy/systemd/ipf3-worker.service" \
  "$REPO/deploy/systemd/ipf3-backup.service" "$REPO/deploy/systemd/ipf3-backup.timer" /etc/systemd/system/
install -m 0644 "$REPO/deploy/nginx/ipf3-proxy.conf" /etc/nginx/snippets/ipf3-proxy.conf
install -m 0644 "$REPO/deploy/nginx/ipf3-headers.conf" /etc/nginx/snippets/ipf3-headers.conf
systemctl daemon-reload

# Stop the worker during migrations so no background job sees a half-migrated schema.
systemctl stop ipf3-worker.service
"$REPO/deploy/install-app.sh" "${APP_ARGS[@]}"
nginx -t && systemctl reload nginx
info "Upgrade complete ($TO). Roll back with deploy/restore.sh and the backup listed above if needed."
