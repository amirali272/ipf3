#!/usr/bin/env bash
# Completely remove Unknown Monitor (panel and/or agent) from this server.
#
#   sudo ./deploy/uninstall.sh                 # asks for confirmation
#   sudo ./deploy/uninstall.sh --yes --remove-backups --remove-packages
#
# Removes: services, timers, application files (/opt/ipf3, /opt/ipf3-agent,
# /opt/unknown-monitor), configuration and secrets (/etc/ipf3), the PostgreSQL
# database and role, the nginx site, the Let's Encrypt certificate for the panel
# domain, the service accounts and logs.
# Kept unless asked: backups in /var/backups/ipf3 and the shared packages
# (postgresql, nginx, certbot, iperf3, ...), which other software may use.
set -uo pipefail

YES=0
REMOVE_BACKUPS=""
REMOVE_PACKAGES=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1; shift ;;
    --remove-backups) REMOVE_BACKUPS=1; shift ;;
    --keep-backups) REMOVE_BACKUPS=0; shift ;;
    --remove-packages) REMOVE_PACKAGES=1; shift ;;
    --keep-packages) REMOVE_PACKAGES=0; shift ;;
    -h|--help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Please run as root: sudo $0" >&2; exit 1; }

if [[ -t 1 ]]; then G=$'\e[38;5;42m'; Y=$'\e[38;5;221m'; RED=$'\e[38;5;203m'; GR=$'\e[38;5;245m'; B=$'\e[1m'; R=$'\e[0m'
else G=""; Y=""; RED=""; GR=""; B=""; R=""; fi
step() { printf '   %s✔%s %s\n' "$G" "$R" "$*"; }
skip() { printf '   %s–%s %s\n' "$GR" "$R" "$*"; }
ask_yn() { # ask_yn "question" default
  local ans hint="y/N"; [[ "$2" == y ]] && hint="Y/n"
  printf '   %s?%s %s %s[%s]%s: ' "$G" "$R" "$1" "$GR" "$hint" "$R" >/dev/tty
  IFS= read -r ans </dev/tty || true
  ans="${ans:-$2}"; [[ "$ans" =~ ^[Yy] ]]
}

HAS_PANEL=0; HAS_AGENT=0
[[ -x /usr/local/bin/xray && -d /etc/ipf3/xray ]] && HAS_AGENT=1
[[ -f /etc/ipf3/server.env || -d /opt/ipf3 || -f /etc/systemd/system/ipf3-api.service ]] && HAS_PANEL=1
[[ -f /etc/ipf3/agent.json || -d /opt/ipf3-agent || -f /etc/systemd/system/ipf3-agent.service ]] && HAS_AGENT=1
if [[ $HAS_PANEL -eq 0 && $HAS_AGENT -eq 0 ]]; then
  echo "Unknown Monitor is not installed on this server."
  exit 0
fi

DOMAIN=""
if [[ -f /etc/nginx/sites-available/ipf3.conf ]]; then
  DOMAIN=$(awk '/server_name/ {gsub(";",""); print $2; exit}' /etc/nginx/sites-available/ipf3.conf)
fi

printf '\n %s%sUninstall Unknown Monitor%s\n\n' "$B" "$RED" "$R"
[[ $HAS_PANEL -eq 1 ]] && printf '   • Panel%s  (database, users, history and traffic statistics will be DELETED)\n' "${DOMAIN:+ at https://$DOMAIN}"
[[ $HAS_AGENT -eq 1 ]] && printf '   • Agent\n'
printf '\n'

if [[ $YES -eq 0 ]]; then
  printf '   %sThis cannot be undone.%s Type %sDELETE%s to continue: ' "$Y" "$R" "$B" "$R" >/dev/tty
  IFS= read -r confirm </dev/tty || true
  [[ "$confirm" == "DELETE" ]] || { echo "   Aborted."; exit 1; }
  if [[ -z "$REMOVE_BACKUPS" && -d /var/backups/ipf3 ]]; then
    if ask_yn "Also delete backups in /var/backups/ipf3?" n; then REMOVE_BACKUPS=1; else REMOVE_BACKUPS=0; fi
  fi
  if [[ -z "$REMOVE_PACKAGES" ]]; then
    if ask_yn "Also remove the packages it installed (postgresql, nginx, certbot, iperf3, mtr, traceroute)? Only if nothing else on this server uses them" n; then
      REMOVE_PACKAGES=1
    else
      REMOVE_PACKAGES=0
    fi
  fi
  printf '\n'
fi
REMOVE_BACKUPS="${REMOVE_BACKUPS:-0}"
REMOVE_PACKAGES="${REMOVE_PACKAGES:-0}"

# --- services ---------------------------------------------------------------
UNITS=(ipf3-api.service ipf3-worker.service ipf3-backup.timer ipf3-backup.service ipf3-agent.service ipf3-iperf3.service
       ipf3-xray-config.path ipf3-xray-reload.service ipf3-xray.service)
for u in "${UNITS[@]}"; do
  systemctl disable --now "$u" >/dev/null 2>&1 || true
  rm -f "/etc/systemd/system/$u"
done
rm -rf /etc/systemd/system/ipf3-api.service.d /etc/systemd/system/ipf3-backup.service.d
systemctl daemon-reload 2>/dev/null || true
systemctl reset-failed >/dev/null 2>&1 || true
step "Services stopped and removed"

# --- database -----------------------------------------------------------------
if command -v psql >/dev/null && systemctl is-active --quiet postgresql 2>/dev/null; then
  runuser -u postgres -- dropdb --if-exists ipf3 >/dev/null 2>&1 && \
  runuser -u postgres -- psql -qc "DROP ROLE IF EXISTS ipf3" >/dev/null 2>&1
  step "Database and database role removed"
else
  skip "PostgreSQL not running — database not touched"
fi

# --- nginx & certificates -----------------------------------------------------
if [[ -e /etc/nginx/sites-enabled/ipf3.conf || -e /etc/nginx/sites-available/ipf3.conf ]]; then
  rm -f /etc/nginx/sites-enabled/ipf3.conf /etc/nginx/sites-available/ipf3.conf \
        /etc/nginx/snippets/ipf3-proxy.conf /etc/nginx/snippets/ipf3-headers.conf
  if command -v nginx >/dev/null && nginx -t >/dev/null 2>&1; then systemctl reload nginx >/dev/null 2>&1 || true; fi
  step "nginx site removed"
fi
if [[ -n "$DOMAIN" && -d "/etc/letsencrypt/live/$DOMAIN" ]] && command -v certbot >/dev/null; then
  certbot delete --cert-name "$DOMAIN" --non-interactive >/dev/null 2>&1 || true
  step "Let's Encrypt certificate for $DOMAIN removed"
fi
rm -f /etc/letsencrypt/renewal-hooks/deploy/ipf3-nginx.sh

# --- files ----------------------------------------------------------------------
rm -rf /opt/ipf3 /opt/ipf3-agent /opt/unknown-monitor /etc/ipf3 /run/ipf3-install.result
if [[ -x /usr/local/bin/xray ]]; then
  rm -f /usr/local/bin/xray
  rm -rf /usr/local/share/xray
  step "Xray-core removed"
fi
rm -f /var/log/unknown-monitor-install.log
step "Application files, configuration and secrets removed"

if [[ "$REMOVE_BACKUPS" == 1 ]]; then
  rm -rf /var/backups/ipf3
  step "Backups removed"
elif [[ -d /var/backups/ipf3 ]]; then
  skip "Backups kept in /var/backups/ipf3"
fi

# --- accounts -------------------------------------------------------------------
for u in ipf3 ipf3-agent ipf3-xray; do
  if id -u "$u" >/dev/null 2>&1; then userdel "$u" >/dev/null 2>&1 || true; fi
  getent group "$u" >/dev/null && groupdel "$u" >/dev/null 2>&1 || true
done
step "Service accounts removed"

# --- packages -------------------------------------------------------------------
if [[ "$REMOVE_PACKAGES" == 1 ]]; then
  DEBIAN_FRONTEND=noninteractive apt-get purge -y -q 'postgresql*' nginx nginx-common certbot iperf3 mtr-tiny traceroute >/dev/null 2>&1 || true
  DEBIAN_FRONTEND=noninteractive apt-get autoremove -y -q >/dev/null 2>&1 || true
  rm -rf /etc/apt/sources.list.d/nodesource.list /etc/apt/keyrings/nodesource.gpg
  step "Packages removed"
else
  skip "Shared packages kept (postgresql, nginx, ...)"
fi

printf '\n   %sUnknown Monitor has been removed from this server.%s\n' "$G" "$R"
[[ $HAS_AGENT -eq 1 && $HAS_PANEL -eq 0 ]] && printf '   %sAlso delete this server in the panel: Servers → (server) → Settings → Delete.%s\n' "$GR" "$R"
printf '   %sThe downloaded source folder (e.g. ~/ipf3) can be deleted with: rm -rf ~/ipf3%s\n\n' "$GR" "$R"
exit 0
