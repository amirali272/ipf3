#!/usr/bin/env bash
# Remove ipf3-agent from this host. Delete the server entry in the UI as well.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_root
systemctl disable --now ipf3-agent.service ipf3-iperf3.service 2>/dev/null || true
rm -f /etc/systemd/system/ipf3-agent.service /etc/systemd/system/ipf3-iperf3.service
systemctl daemon-reload
rm -rf /opt/ipf3-agent
rm -f /etc/ipf3/agent.json /etc/ipf3/iperf3.env /etc/ipf3/server-ca.pem
rmdir /etc/ipf3 2>/dev/null || true
userdel ipf3-agent 2>/dev/null || true
info "ipf3-agent removed"
