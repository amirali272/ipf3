#!/usr/bin/env bash
# Upgrade ipf3-agent in place from this checkout (keeps enrollment and settings).
#   git pull && sudo ./deploy/upgrade-agent.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_root
REPO="$(repo_root)"
PREFIX=/opt/ipf3-agent
[[ -f /etc/ipf3/agent.json ]] || die "agent is not installed/enrolled (run install-agent.sh)"
"$PREFIX/venv/bin/pip" install -q -r "$REPO/agent/requirements.lock"
"$PREFIX/venv/bin/pip" install -q --no-deps --force-reinstall "$REPO/agent"
install -m 0644 "$REPO/deploy/systemd/ipf3-agent.service" /etc/systemd/system/
[[ -f /etc/systemd/system/ipf3-iperf3.service ]] && install -m 0644 "$REPO/deploy/systemd/ipf3-iperf3.service" /etc/systemd/system/
systemctl daemon-reload
systemctl restart ipf3-agent.service
sleep 2
systemctl is-active --quiet ipf3-agent.service || die "agent failed to start: journalctl -u ipf3-agent"
info "ipf3-agent upgraded to $("$PREFIX/venv/bin/python" -c 'import ipf3_agent; print(ipf3_agent.__version__)')"
