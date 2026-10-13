#!/usr/bin/env bash
# Install ipf3-agent on an Ubuntu server and enroll it with the IPF3 server.
#
#   sudo ./deploy/install-agent.sh --server https://ipf3.example.com --token ipf3e_xxx [--name edge-1]
#                                  [--ca-file /path/ca.pem] [--iperf3-server [--iperf3-port 5201]]
#
# Re-running upgrades the agent code in place and keeps the existing enrollment.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SERVER=""
TOKEN="${IPF3_ENROLLMENT_TOKEN:-}"
NAME="$(hostname -s)"
CA_FILE=""
IPERF3_SERVER=0
IPERF3_PORT=5201
REENROLL=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server) SERVER="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --name) NAME="$2"; shift 2 ;;
    --ca-file) CA_FILE="$2"; shift 2 ;;
    --iperf3-server) IPERF3_SERVER=1; shift ;;
    --iperf3-port) IPERF3_PORT="$2"; shift 2 ;;
    --reenroll) REENROLL=1; shift ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

require_root
require_ubuntu
REPO="$(repo_root)"
PREFIX=/opt/ipf3-agent
CONF=/etc/ipf3/agent.json

[[ "$NAME" =~ ^[A-Za-z0-9_.@-]{1,128}$ ]] || die "invalid --name"
[[ "$IPERF3_PORT" =~ ^[0-9]+$ && "$IPERF3_PORT" -ge 1 && "$IPERF3_PORT" -le 65535 ]] || die "invalid --iperf3-port"
if [[ ! -f "$CONF" || $REENROLL -eq 1 ]]; then
  [[ "$SERVER" == https://* ]] || die "--server https://... is required for enrollment"
  [[ -n "$TOKEN" ]] || die "--token (or IPF3_ENROLLMENT_TOKEN) is required for enrollment"
fi
[[ -z "$CA_FILE" || -r "$CA_FILE" ]] || die "--ca-file is not readable"

info "Installing packages (measurement tools come from the Ubuntu archive)"
echo "iperf3 iperf3/start_daemon boolean false" | debconf-set-selections
apt-get update -q
apt_install python3 python3-venv iperf3 iputils-ping traceroute mtr-tiny iproute2 ca-certificates
python_ok || die "Python >= 3.10 is required"

info "Creating service account"
ensure_system_user ipf3-agent "$PREFIX"
install -d -m 0755 -o root -g root "$PREFIX"
ensure_etc_dir

info "Installing agent into $PREFIX"
[[ -x "$PREFIX/venv/bin/python" ]] || python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install -q --upgrade pip
"$PREFIX/venv/bin/pip" install -q -r "$REPO/agent/requirements.lock"
"$PREFIX/venv/bin/pip" install -q --no-deps --force-reinstall "$REPO/agent"

if [[ -n "$CA_FILE" ]]; then
  install -m 0644 "$CA_FILE" /etc/ipf3/server-ca.pem
  CA_ARG=(--ca-file /etc/ipf3/server-ca.pem)
else
  CA_ARG=()
fi

if [[ ! -f "$CONF" || $REENROLL -eq 1 ]]; then
  info "Enrolling '$NAME' with $SERVER"
  FORCE_ARG=()
  [[ $REENROLL -eq 1 ]] && FORCE_ARG=(--force)
  IPF3_ENROLLMENT_TOKEN="$TOKEN" "$PREFIX/venv/bin/ipf3-agent" --config "$CONF" enroll \
    --server "$SERVER" --name "$NAME" "${CA_ARG[@]}" "${FORCE_ARG[@]}"
else
  info "Existing enrollment found in $CONF; keeping it"
fi
# Secret is readable by the agent account only (and root).
chown root:ipf3-agent "$CONF"
chmod 0640 "$CONF"

info "Installing systemd units"
install -m 0644 "$REPO/deploy/systemd/ipf3-agent.service" /etc/systemd/system/
if [[ $IPERF3_SERVER -eq 1 ]]; then
  install -m 0644 "$REPO/deploy/systemd/ipf3-iperf3.service" /etc/systemd/system/
  printf 'IPF3_IPERF3_PORT=%s\n' "$IPERF3_PORT" > /etc/ipf3/iperf3.env
  systemctl disable --now iperf3.service >/dev/null 2>&1 || true
fi
systemctl daemon-reload
systemctl enable ipf3-agent.service
systemctl restart ipf3-agent.service
if [[ $IPERF3_SERVER -eq 1 ]]; then
  systemctl enable --now ipf3-iperf3.service
  if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    warn "ufw is active: allow iperf3 only from your test sources, e.g.: ufw allow from 10.0.0.0/8 to any port $IPERF3_PORT proto tcp && ufw allow from 10.0.0.0/8 to any port $IPERF3_PORT proto udp"
  fi
fi

sleep 3
if systemctl is-active --quiet ipf3-agent.service; then
  info "ipf3-agent is running. Logs: journalctl -u ipf3-agent -f"
else
  journalctl -u ipf3-agent -n 30 --no-pager || true
  die "ipf3-agent failed to start"
fi
