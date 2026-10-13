#!/usr/bin/env bash
# Install or upgrade Xray-core for an Unknown Monitor VPN node.
#   sudo ./deploy/install-xray.sh            # latest release
#   XRAY_VERSION=v26.3.27 sudo ./deploy/install-xray.sh
# The release zip is verified against the SHA-256 published next to it.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
require_root
REPO="$(repo_root)"

case "$(uname -m)" in
  x86_64|amd64) ARCH=64 ;;
  aarch64|arm64) ARCH=arm64-v8a ;;
  armv7l) ARCH=arm32-v7a ;;
  *) die "unsupported architecture $(uname -m)" ;;
esac
if [[ -n "${XRAY_VERSION:-}" ]]; then
  BASE="https://github.com/XTLS/Xray-core/releases/download/${XRAY_VERSION}"
else
  BASE="https://github.com/XTLS/Xray-core/releases/latest/download"
fi

apt_install unzip curl ca-certificates >/dev/null
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
info "Downloading Xray-core (${XRAY_VERSION:-latest}, linux-$ARCH)"
curl -fsSL --retry 3 -o "$TMP/xray.zip" "$BASE/Xray-linux-$ARCH.zip"
curl -fsSL --retry 3 -o "$TMP/xray.dgst" "$BASE/Xray-linux-$ARCH.zip.dgst"
EXPECTED=$(awk -F'= ' '/^SHA2-256=/ {print $2}' "$TMP/xray.dgst" | tr -d '[:space:]')
ACTUAL=$(sha256sum "$TMP/xray.zip" | cut -d' ' -f1)
[[ -n "$EXPECTED" && "$EXPECTED" == "$ACTUAL" ]] || die "checksum mismatch for Xray download (expected $EXPECTED, got $ACTUAL)"
unzip -q -o "$TMP/xray.zip" -d "$TMP/x"
install -m 0755 "$TMP/x/xray" /usr/local/bin/xray
install -d -m 0755 /usr/local/share/xray
install -m 0644 "$TMP/x/geoip.dat" "$TMP/x/geosite.dat" /usr/local/share/xray/

ensure_system_user ipf3-xray /nonexistent
ensure_etc_dir
id -u ipf3-agent >/dev/null 2>&1 || ensure_system_user ipf3-agent /opt/ipf3-agent
# Agent writes the config, Xray reads it.
install -d -m 0750 -o ipf3-agent -g ipf3-xray /etc/ipf3/xray
if [[ ! -f /etc/ipf3/xray/config.json ]]; then
  # Minimal placeholder until the panel sends the real config (API only, no open ports).
  cat > /etc/ipf3/xray/config.json <<'JSON'
{"log":{"loglevel":"warning"},"api":{"tag":"api","services":["StatsService"]},"stats":{},
 "inbounds":[{"tag":"api","listen":"127.0.0.1","port":10085,"protocol":"dokodemo-door","settings":{"address":"127.0.0.1"}}],
 "outbounds":[{"protocol":"freedom"}],"routing":{"rules":[{"type":"field","inboundTag":["api"],"outboundTag":"api"}]}}
JSON
  chown ipf3-agent:ipf3-xray /etc/ipf3/xray/config.json
  chmod 0640 /etc/ipf3/xray/config.json
fi

install -m 0644 "$REPO/deploy/systemd/ipf3-xray.service" "$REPO/deploy/systemd/ipf3-xray-config.path" \
  "$REPO/deploy/systemd/ipf3-xray-reload.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now ipf3-xray-config.path >/dev/null
systemctl enable ipf3-xray.service >/dev/null
systemctl restart ipf3-xray.service
info "Xray $(/usr/local/bin/xray version | awk 'NR==1{print $2}') installed"
