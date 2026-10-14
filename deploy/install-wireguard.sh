#!/usr/bin/env bash
# Install or upgrade WireGuard support for an Unknown Monitor VPN node.
#   sudo ./deploy/install-wireguard.sh
#
# wg0 itself is only created once the panel pushes a WireGuard inbound for this
# node (VPN → Inbounds & nodes). This script installs the tools and the units that
# apply whatever config the agent writes — see docs/VPN.md.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_root
REPO="$(repo_root)"

info "Installing wireguard-tools"
apt_install wireguard-tools

# The kernel module ships with Ubuntu 22.04/24.04's kernel; if it's somehow
# unavailable wg-quick itself falls back to the slower userspace implementation
# (wireguard-go) automatically, so nothing here depends on the module directly.

info "Enabling IP forwarding (needed to route peers' traffic onward)"
install -d -m 0755 /etc/sysctl.d
cat > /etc/sysctl.d/99-ipf3-wireguard.conf <<'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl -q -p /etc/sysctl.d/99-ipf3-wireguard.conf 2>/dev/null || true

id -u ipf3-agent >/dev/null 2>&1 || ensure_system_user ipf3-agent /opt/ipf3-agent
ensure_etc_dir
# Only the agent writes here (its desired config); only root ever reads it, to
# copy into /etc/wireguard/wg0.conf — see ipf3-wireguard-reload.service.
install -d -m 0750 -o ipf3-agent -g ipf3-agent /etc/ipf3/wireguard

install -d -m 0755 -o root -g root /opt/ipf3-agent
install -m 0755 -o root -g root "$REPO/deploy/wg-stats.sh" /opt/ipf3-agent/wg-stats.sh

install -d -m 0755 /etc/systemd/system/wg-quick@wg0.service.d
install -m 0644 "$REPO/deploy/systemd/wg-quick@wg0.service.d/ipf3.conf" /etc/systemd/system/wg-quick@wg0.service.d/
install -m 0644 "$REPO/deploy/systemd/ipf3-wireguard-config.path" "$REPO/deploy/systemd/ipf3-wireguard-reload.service" \
  "$REPO/deploy/systemd/ipf3-wireguard-stats.service" "$REPO/deploy/systemd/ipf3-wireguard-stats.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ipf3-wireguard-config.path ipf3-wireguard-stats.timer >/dev/null
# Boot-persistence only — wg-quick@wg0 won't actually start until
# /etc/wireguard/wg0.conf exists (the drop-in's ConditionPathExists).
systemctl enable wg-quick@wg0.service >/dev/null 2>&1 || true

info "WireGuard tooling installed"
