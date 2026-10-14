#!/usr/bin/env bash
# Dumps wg0 peer stats to a world-readable file for the (unprivileged) ipf3-agent
# to read. Reading WireGuard peer state — even just byte counters and handshake
# times — needs root or CAP_NET_ADMIN, which the agent deliberately doesn't have
# (same reasoning as the rest of its sandboxing). Run every ~10s by
# ipf3-wireguard-stats.timer, as root.
set -euo pipefail
OUT=/run/ipf3-wg/stats.dump
TMP="$OUT.tmp.$$"
trap 'rm -f "$TMP"' EXIT
install -d -m 0755 "$(dirname "$OUT")"  # normally created by RuntimeDirectory=; defensive otherwise

if ip link show wg0 &>/dev/null; then
  wg show wg0 dump > "$TMP" 2>/dev/null || : > "$TMP"
else
  : > "$TMP"  # no interface yet (or torn down): report no peers, not stale ones
fi
chmod 0644 "$TMP"
mv -f "$TMP" "$OUT"
