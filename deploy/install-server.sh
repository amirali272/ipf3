#!/usr/bin/env bash
# Install the Unknown Monitor control plane (API, worker, PostgreSQL, nginx, web UI) on Ubuntu.
# For a guided installation run ./install.sh instead.
#
#   sudo ./deploy/install-server.sh --domain monitor.example.com --tls auto
#   sudo ./deploy/install-server.sh --domain monitor.example.com --tls letsencrypt --email ops@example.com
#   sudo ./deploy/install-server.sh --domain 10.0.0.5 --tls self-signed
#   sudo ./deploy/install-server.sh --domain ipf3.corp --tls existing --cert /path/fullchain.pem --key /path/key.pem
#
# Idempotent: re-running keeps the existing secret key, database and admin user.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

DOMAIN=""
TLS_MODE="auto"
TIMEZONE=""
EMAIL=""
CERT=""
KEY=""
ADMIN_USER="admin"
WORKERS=2
CONFIGURE_UFW=0
SKIP_WEB_BUILD=0

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
  cat <<USAGE

Options:
  --domain NAME          DNS name or IP clients use to reach the UI (required)
  --tls MODE             auto | letsencrypt | self-signed | existing   (default: auto =
                         Let's Encrypt for a resolvable domain, falling back to self-signed)
  --email ADDR           ACME account email (optional)
  --timezone ZONE        calendar for daily/monthly usage, e.g. Asia/Tehran (default: system)
  --cert PATH --key PATH certificate and key (existing)
  --admin-user NAME      administrator account (default: admin)
                         Set IPF3_ADMIN_PASSWORD in the environment to choose its password;
                         otherwise a random one is generated and printed once.
  --workers N            uvicorn worker processes (default: 2)
  --ufw                  allow 80/443 (and OpenSSH) in ufw and enable it
  --skip-web-build       use a prebuilt web/dist instead of building with Node.js
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --tls) TLS_MODE="$2"; shift 2 ;;
    --email) EMAIL="$2"; shift 2 ;;
    --timezone) TIMEZONE="$2"; shift 2 ;;
    --cert) CERT="$2"; shift 2 ;;
    --key) KEY="$2"; shift 2 ;;
    --admin-user) ADMIN_USER="$2"; shift 2 ;;
    --workers) WORKERS="$2"; shift 2 ;;
    --ufw) CONFIGURE_UFW=1; shift ;;
    --skip-web-build) SKIP_WEB_BUILD=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1 (see --help)" ;;
  esac
done

require_root
require_ubuntu
if [[ $SKIP_WEB_BUILD -eq 0 ]] && prebuilt_web_ok "$(repo_root)"; then
  SKIP_WEB_BUILD=1   # prebuilt UI matches the sources: no Node.js needed
fi
[[ -n "$DOMAIN" ]] || { usage; die "--domain is required"; }
[[ "$DOMAIN" =~ ^[A-Za-z0-9.:-]+$ ]] || die "invalid --domain"
[[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] || die "invalid --admin-user"
[[ "$WORKERS" =~ ^[0-9]+$ ]] || die "invalid --workers"
is_ip() { [[ "$1" =~ ^[0-9.]+$ || "$1" == *:* ]]; }
is_placeholder() { [[ "$1" =~ (^|\.)(example\.(com|net|org)|localhost|local|test|invalid|lan|internal)$ ]]; }
case "$TLS_MODE" in
  auto)
    if is_ip "$DOMAIN" || is_placeholder "$DOMAIN" || ! getent ahosts "$DOMAIN" >/dev/null 2>&1; then
      TLS_MODE="self-signed"
    else
      TLS_MODE="letsencrypt"; TLS_FALLBACK=1
    fi
    ;;
  letsencrypt)
    is_ip "$DOMAIN" && die "Let's Encrypt cannot issue certificates for IP addresses. Use a real domain name, or: --tls self-signed"
    is_placeholder "$DOMAIN" && die "'$DOMAIN' is a placeholder/reserved name. Use a real domain whose DNS A record points to this server, or: --tls self-signed"
    getent ahosts "$DOMAIN" >/dev/null 2>&1 || die "'$DOMAIN' does not resolve in DNS. Create an A/AAAA record pointing to this server first, or use: --tls self-signed"
    ;;
  existing) [[ -r "$CERT" && -r "$KEY" ]] || die "--cert and --key must be readable files" ;;
  self-signed) ;;
  *) die "--tls must be auto, letsencrypt, self-signed or existing" ;;
esac
TLS_FALLBACK="${TLS_FALLBACK:-0}"
if [[ -n "${IPF3_ADMIN_PASSWORD:-}" ]]; then
  pw="$IPF3_ADMIN_PASSWORD"; classes=0
  [[ "$pw" =~ [a-z] ]] && classes=$((classes + 1))
  [[ "$pw" =~ [A-Z] ]] && classes=$((classes + 1))
  [[ "$pw" =~ [0-9] ]] && classes=$((classes + 1))
  [[ "$pw" =~ [^A-Za-z0-9] ]] && classes=$((classes + 1))
  { [[ ${#pw} -ge 12 ]] && [[ $classes -ge 3 ]]; } || die "IPF3_ADMIN_PASSWORD must be at least 12 characters with 3 of: lowercase, uppercase, digit, symbol"
fi

REPO="$(repo_root)"
PREFIX=/opt/ipf3
ETC=/etc/ipf3

info "Installing system packages"
apt-get update -q
apt_install python3 python3-venv python3-pip postgresql postgresql-contrib nginx openssl ca-certificates curl rsync
python_ok || die "Python >= 3.10 is required"

# --- Node.js (build only) ---------------------------------------------------
node_ok() { command -v node >/dev/null && node -e 'process.exit(+process.versions.node.split(".")[0] >= 18 ? 0 : 1)'; }
if [[ $SKIP_WEB_BUILD -eq 0 ]] && ! node_ok; then
  if [[ "${UBUNTU_VERSION%%.*}" -ge 24 ]]; then
    info "Installing Node.js from Ubuntu archive (build dependency)"
    apt_install nodejs npm
  else
    info "Installing Node.js 20 from the NodeSource apt repository (build dependency)"
    install -d -m 0755 /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list
    apt-get update -q && apt_install nodejs
  fi
  node_ok || die "Node.js >= 18 is required to build the web UI (or pass --skip-web-build with web/dist present)"
fi

info "Creating service account and directories"
ensure_system_user ipf3 "$PREFIX"
install -d -m 0755 -o root -g root "$PREFIX" "$PREFIX/deploy"
ensure_etc_dir
install -d -m 0700 -o postgres -g postgres /var/backups/ipf3

info "Configuring PostgreSQL (unix-socket peer authentication, no password)"
systemctl enable --now postgresql
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='ipf3'" | grep -q 1; then
  runuser -u postgres -- createuser --no-superuser --no-createdb --no-createrole ipf3
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='ipf3'" | grep -q 1; then
  runuser -u postgres -- createdb --owner=ipf3 --encoding=UTF8 ipf3
fi
runuser -u postgres -- psql -q -d ipf3 -c "REVOKE ALL ON DATABASE ipf3 FROM PUBLIC; REVOKE CREATE ON SCHEMA public FROM PUBLIC; ALTER SCHEMA public OWNER TO ipf3;"

info "Writing configuration"
if [[ ! -f "$ETC/server.env" ]]; then
  umask 027
  cat > "$ETC/server.env" <<ENV
# IPF3 server configuration. See docs/CONFIGURATION.md for all options.
IPF3_DATABASE_URL=postgresql+asyncpg://ipf3@/ipf3?host=/var/run/postgresql
IPF3_SECRET_KEY=$(openssl rand -hex 32)
IPF3_COOKIE_SECURE=true
IPF3_TRUSTED_PROXIES=127.0.0.1,::1
IPF3_FORWARDED_ALLOW_IPS=127.0.0.1
IPF3_AGENT_OFFLINE_SECONDS=90
IPF3_RETENTION_METRICS_DAYS=30
IPF3_RETENTION_JOBS_DAYS=180
# IPF3_SMTP_HOST=smtp.example.com
# IPF3_SMTP_PORT=587
# IPF3_SMTP_USER=
# IPF3_SMTP_PASSWORD=
# IPF3_SMTP_FROM=ipf3@example.com
ENV
  umask 022
fi
chown root:ipf3 "$ETC/server.env"
chmod 0640 "$ETC/server.env"
if [[ -n "$TIMEZONE" ]]; then
  if [[ -f "/usr/share/zoneinfo/$TIMEZONE" ]]; then
    sed -i '/^IPF3_USAGE_TIMEZONE=/d' "$ETC/server.env"
    printf 'IPF3_USAGE_TIMEZONE=%s\n' "$TIMEZONE" >> "$ETC/server.env"
  else
    warn "unknown timezone '$TIMEZONE'; keeping the default"
  fi
fi

info "Installing application into $PREFIX"
APP_ARGS=(--skip-restart)
[[ $SKIP_WEB_BUILD -eq 1 ]] && APP_ARGS+=(--skip-web-build)
"$REPO/deploy/install-app.sh" "${APP_ARGS[@]}"

info "Installing systemd units"
install -m 0644 "$REPO/deploy/systemd/ipf3-api.service" "$REPO/deploy/systemd/ipf3-worker.service" \
  "$REPO/deploy/systemd/ipf3-backup.service" "$REPO/deploy/systemd/ipf3-backup.timer" /etc/systemd/system/
install -d /etc/systemd/system/ipf3-api.service.d
printf '[Service]\nEnvironment=IPF3_WORKERS=%s\n' "$WORKERS" > /etc/systemd/system/ipf3-api.service.d/workers.conf
systemctl daemon-reload

info "Configuring TLS ($TLS_MODE)"
install -d -m 0755 /var/www/letsencrypt
case "$TLS_MODE" in
  self-signed)
    CERT=/etc/ipf3/tls/server.crt; KEY=/etc/ipf3/tls/server.key
    install -d -m 0750 -o root -g root /etc/ipf3/tls
    if [[ -f "$CERT" ]] && ! openssl x509 -in "$CERT" -noout -checkhost "$DOMAIN" 2>/dev/null | grep -q "does match" \
       && ! openssl x509 -in "$CERT" -noout -checkip "$DOMAIN" 2>/dev/null | grep -q "does match"; then
      rm -f "$CERT" "$KEY"   # domain changed: issue a new certificate
    fi
    if [[ ! -f "$CERT" ]]; then
      if is_ip "$DOMAIN"; then SAN="IP:$DOMAIN"; else SAN="DNS:$DOMAIN"; fi
      openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes -keyout "$KEY" -out "$CERT" \
        -subj "/CN=$DOMAIN" -addext "subjectAltName=$SAN" 2>/dev/null
      chmod 0600 "$KEY"
    fi
    ;;
  existing) ;;
  letsencrypt)
    CERT=/etc/letsencrypt/live/$DOMAIN/fullchain.pem; KEY=/etc/letsencrypt/live/$DOMAIN/privkey.pem
    ;;
esac

render_nginx() {
  local cert="$1" key="$2"
  install -m 0644 "$REPO/deploy/nginx/ipf3-proxy.conf" /etc/nginx/snippets/ipf3-proxy.conf
  install -m 0644 "$REPO/deploy/nginx/ipf3-headers.conf" /etc/nginx/snippets/ipf3-headers.conf
  sed -e "s|__DOMAIN__|$DOMAIN|g" -e "s|__CERT__|$cert|g" -e "s|__KEY__|$key|g" \
    "$REPO/deploy/nginx/ipf3.conf.template" > /etc/nginx/sites-available/ipf3.conf
  ln -sf /etc/nginx/sites-available/ipf3.conf /etc/nginx/sites-enabled/ipf3.conf
  rm -f /etc/nginx/sites-enabled/default
}

if [[ "$TLS_MODE" == "letsencrypt" && ! -f "$CERT" ]]; then
  apt_install certbot
  # Temporary self-signed cert so nginx can start and answer the HTTP-01 challenge.
  install -d -m 0750 /etc/ipf3/tls
  openssl req -x509 -newkey rsa:2048 -days 2 -nodes -keyout /etc/ipf3/tls/bootstrap.key \
    -out /etc/ipf3/tls/bootstrap.crt -subj "/CN=$DOMAIN" 2>/dev/null
  render_nginx /etc/ipf3/tls/bootstrap.crt /etc/ipf3/tls/bootstrap.key
  nginx -t && systemctl reload-or-restart nginx
  if [[ -n "$EMAIL" ]]; then ACME_ID=(--email "$EMAIL"); else ACME_ID=(--register-unsafely-without-email); fi
  info "Requesting a Let's Encrypt certificate for $DOMAIN"
  if timeout 240 certbot certonly --webroot -w /var/www/letsencrypt -d "$DOMAIN" "${ACME_ID[@]}" --agree-tos --non-interactive; then
    install -d /etc/letsencrypt/renewal-hooks/deploy
    printf '#!/bin/sh\nsystemctl reload nginx\n' > /etc/letsencrypt/renewal-hooks/deploy/ipf3-nginx.sh
    chmod 0755 /etc/letsencrypt/renewal-hooks/deploy/ipf3-nginx.sh
  elif [[ $TLS_FALLBACK -eq 1 ]]; then
    warn "Let's Encrypt failed (is '$DOMAIN' pointing here and port 80 open?). Using a self-signed certificate instead; re-run later to retry."
    TLS_MODE="self-signed"
    CERT=/etc/ipf3/tls/server.crt; KEY=/etc/ipf3/tls/server.key
    if is_ip "$DOMAIN"; then SAN="IP:$DOMAIN"; else SAN="DNS:$DOMAIN"; fi
    openssl req -x509 -newkey rsa:3072 -sha256 -days 825 -nodes -keyout "$KEY" -out "$CERT" \
      -subj "/CN=$DOMAIN" -addext "subjectAltName=$SAN" 2>/dev/null
    chmod 0600 "$KEY"
  else
    die "certbot failed. Check that '$DOMAIN' points to this server and that TCP port 80 is reachable from the internet, then re-run this script (it is safe to re-run). Alternatively use: --tls self-signed"
  fi
fi
render_nginx "$CERT" "$KEY"
nginx -t
systemctl enable nginx
systemctl reload-or-restart nginx

if [[ $CONFIGURE_UFW -eq 1 ]]; then
  apt_install ufw
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw --force enable
fi

info "Starting services (API, worker, backups)"
systemctl enable --now ipf3-api.service ipf3-worker.service ipf3-backup.timer
for _ in $(seq 1 30); do
  curl -fsS http://127.0.0.1:8000/readyz >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS http://127.0.0.1:8000/readyz >/dev/null || die "API did not become ready; see: journalctl -u ipf3-api"

ADMIN_EXISTS=$(runuser -u postgres -- psql -d ipf3 -tAc "SELECT count(*) FROM users WHERE role='admin'")
GENERATED_PASSWORD=""
if [[ -n "${IPF3_ADMIN_PASSWORD:-}" ]]; then
  printf '%s\n' "$IPF3_ADMIN_PASSWORD" | ipf3_cli create-user "$ADMIN_USER" --role admin --update >/dev/null
  info "Administrator '$ADMIN_USER' is ready"
elif [[ "$ADMIN_EXISTS" == "0" ]]; then
  GENERATED_PASSWORD="$(openssl rand -base64 18 | tr -d '/+=')Aa1!"
  printf '%s\n' "$GENERATED_PASSWORD" | ipf3_cli create-user "$ADMIN_USER" --role admin >/dev/null
fi

# Machine-readable result for install.sh
printf 'DOMAIN=%s\nTLS_MODE=%s\nCERT=%s\n' "$DOMAIN" "$TLS_MODE" "$CERT" > /run/ipf3-install.result

if [[ "${IPF3_QUIET_SUMMARY:-0}" != "1" ]]; then
  printf '\n%sUnknown Monitor is running at https://%s/%s\n' "$C_BOLD" "$DOMAIN" "$C_RESET"
  if [[ -n "$GENERATED_PASSWORD" ]]; then
    printf '  user:     %s\n  password: %s\n  (shown once — change it after first login under Account)\n' "$ADMIN_USER" "$GENERATED_PASSWORD"
  fi
  if [[ "$TLS_MODE" == "self-signed" ]]; then
    echo "  Self-signed certificate SHA-256: $(openssl x509 -in "$CERT" -noout -fingerprint -sha256 | cut -d= -f2)"
  fi
  echo "Next: Servers → Enroll server, then run ./install.sh on each Ubuntu host."
fi
