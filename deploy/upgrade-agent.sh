#!/usr/bin/env bash
# Upgrade ipf3-agent in place from this checkout (keeps enrollment and settings).
#   git pull && sudo ./deploy/upgrade-agent.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_root
REPO="$(repo_root)"
PREFIX=/opt/ipf3-agent
[[ -f /etc/ipf3/agent.json ]] || die "agent is not installed/enrolled (run install-agent.sh)"
ensure_etc_dir
chown root:ipf3-agent /etc/ipf3/agent.json && chmod 0640 /etc/ipf3/agent.json
"$PREFIX/venv/bin/pip" install -q -r "$REPO/agent/requirements.lock"
"$PREFIX/venv/bin/pip" install -q --no-deps --force-reinstall "$REPO/agent"
install -m 0644 "$REPO/deploy/systemd/ipf3-agent.service" /etc/systemd/system/
[[ -f /etc/systemd/system/ipf3-iperf3.service ]] && install -m 0644 "$REPO/deploy/systemd/ipf3-iperf3.service" /etc/systemd/system/
if [[ -d /etc/ipf3/xray ]]; then
  chown ipf3-agent:ipf3-xray /etc/ipf3/xray && chmod 2750 /etc/ipf3/xray
  find /etc/ipf3/xray -maxdepth 1 -type f -exec chgrp ipf3-xray {} + -exec chmod 0640 {} +
fi
if [[ -f /etc/systemd/system/ipf3-xray.service ]]; then
  install -m 0644 "$REPO/deploy/systemd/ipf3-xray.service" "$REPO/deploy/systemd/ipf3-xray-config.path" \
    "$REPO/deploy/systemd/ipf3-xray-reload.service" /etc/systemd/system/
fi
if [[ -d /etc/ipf3/wireguard ]]; then
  chown ipf3-agent:ipf3-agent /etc/ipf3/wireguard && chmod 0750 /etc/ipf3/wireguard
fi
if [[ -f /etc/systemd/system/ipf3-wireguard-reload.service ]]; then
  install -m 0755 -o root -g root "$REPO/deploy/wg-stats.sh" /opt/ipf3-agent/wg-stats.sh
  install -d -m 0755 /etc/systemd/system/wg-quick@wg0.service.d
  install -m 0644 "$REPO/deploy/systemd/wg-quick@wg0.service.d/ipf3.conf" /etc/systemd/system/wg-quick@wg0.service.d/
  install -m 0644 "$REPO/deploy/systemd/ipf3-wireguard-config.path" "$REPO/deploy/systemd/ipf3-wireguard-reload.service" \
    "$REPO/deploy/systemd/ipf3-wireguard-stats.service" "$REPO/deploy/systemd/ipf3-wireguard-stats.timer" /etc/systemd/system/
fi
systemctl daemon-reload
systemctl restart ipf3-agent.service
sleep 2
systemctl is-active --quiet ipf3-agent.service || die "agent failed to start: journalctl -u ipf3-agent"
info "ipf3-agent upgraded to $("$PREFIX/venv/bin/python" -c 'import ipf3_agent; print(ipf3_agent.__version__)')"
