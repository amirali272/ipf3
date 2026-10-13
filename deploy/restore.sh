#!/usr/bin/env bash
# Restore an IPF3 database backup (and optionally configuration).
#   sudo ./deploy/restore.sh /var/backups/ipf3/ipf3-db-20260101T021700Z.dump [--config ipf3-config-....tar.gz]
# Stops the API and worker, replaces the database, runs migrations, restarts.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
DUMP="${1:-}"; shift || true
CONFIG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done
[[ -r "$DUMP" ]] || { echo "usage: $0 <db.dump> [--config <config.tar.gz>]" >&2; exit 1; }
SUMS="$(dirname "$DUMP")/ipf3-$(basename "$DUMP" | sed -E 's/^ipf3-db-(.*)\.dump$/\1/').sha256"
if [[ -f "$SUMS" ]]; then
  ( cd "$(dirname "$DUMP")" && sha256sum --check --ignore-missing "$(basename "$SUMS")" )
fi
runuser -u postgres -- pg_restore --list "$DUMP" >/dev/null

read -r -p "This REPLACES the current IPF3 database. Type 'restore' to continue: " ok
[[ "$ok" == "restore" ]] || { echo "aborted"; exit 1; }

systemctl stop ipf3-worker.service ipf3-api.service
if [[ -n "$CONFIG" ]]; then
  tar -C / -xzf "$CONFIG" etc/ipf3
  chown -R root:ipf3 /etc/ipf3 && chmod 0750 /etc/ipf3 && chmod 0640 /etc/ipf3/server.env
fi
TMP_DUMP=$(mktemp /tmp/ipf3-restore.XXXXXX)
install -m 0600 -o postgres -g postgres "$DUMP" "$TMP_DUMP"
runuser -u postgres -- dropdb --if-exists ipf3
runuser -u postgres -- createdb --owner=ipf3 --encoding=UTF8 ipf3
runuser -u postgres -- psql -q -d ipf3 -c "ALTER SCHEMA public OWNER TO ipf3; REVOKE ALL ON DATABASE ipf3 FROM PUBLIC; REVOKE CREATE ON SCHEMA public FROM PUBLIC;"
runuser -u postgres -- pg_restore --no-owner --role=ipf3 --dbname=ipf3 --exit-on-error "$TMP_DUMP"
rm -f "$TMP_DUMP"
runuser -u ipf3 -- bash -c 'set -a; . /etc/ipf3/server.env; set +a; exec /opt/ipf3/venv/bin/ipf3-server migrate'
systemctl start ipf3-api.service ipf3-worker.service
echo "restore complete"
