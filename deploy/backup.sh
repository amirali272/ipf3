#!/usr/bin/env bash
# Back up the IPF3 database (pg_dump custom format) and configuration.
#   sudo /opt/ipf3/deploy/backup.sh            # also run daily by ipf3-backup.timer
# Env: IPF3_BACKUP_DIR (default /var/backups/ipf3), IPF3_BACKUP_KEEP_DAYS (default 14)
set -euo pipefail
DIR="${IPF3_BACKUP_DIR:-/var/backups/ipf3}"
KEEP="${IPF3_BACKUP_KEEP_DAYS:-14}"
[[ $EUID -eq 0 ]] || { echo "run as root" >&2; exit 1; }
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 -o postgres -g postgres "$DIR"
umask 077

DB="$DIR/ipf3-db-$STAMP.dump"
runuser -u postgres -- pg_dump --format=custom --compress=6 --no-owner --dbname=ipf3 --file="$DB.partial"
mv "$DB.partial" "$DB"
# Validate the archive is readable before declaring success.
runuser -u postgres -- pg_restore --list "$DB" >/dev/null

CFG="$DIR/ipf3-config-$STAMP.tar.gz"
PATHS=(etc/ipf3)
[[ -f /etc/nginx/sites-available/ipf3.conf ]] && PATHS+=(etc/nginx/sites-available/ipf3.conf)
tar -C / -czf "$CFG" "${PATHS[@]}"
chmod 0600 "$DB" "$CFG"
( cd "$DIR" && sha256sum "$(basename "$DB")" "$(basename "$CFG")" > "ipf3-$STAMP.sha256" )

find "$DIR" -maxdepth 1 -type f -name 'ipf3-*' -mtime +"$KEEP" -delete
echo "backup written: $DB ($(du -h "$DB" | cut -f1)), $CFG"
