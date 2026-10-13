# shellcheck shell=bash disable=SC2034
# Shared helpers for IPF3 install / upgrade scripts. Sourced, not executed.
set -euo pipefail

C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'; C_BOLD=$'\e[1m'; C_RESET=$'\e[0m'
info()  { printf '%s==>%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn()  { printf '%s!!%s  %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
die()   { printf '%sERROR:%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }

require_root() { [[ $EUID -eq 0 ]] || die "run as root (sudo $0 ...)"; }

require_ubuntu() {
  [[ -r /etc/os-release ]] || die "cannot detect OS"
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "Ubuntu is required (found ${ID:-unknown})"
  case "${VERSION_ID:-}" in
    22.04|24.04|24.10|25.04|25.10|26.04) ;;
    *) warn "untested Ubuntu release ${VERSION_ID:-?}; continuing" ;;
  esac
  UBUNTU_VERSION="${VERSION_ID}"
}

apt_install() {
  DEBIAN_FRONTEND=noninteractive apt-get install -y -q --no-install-recommends "$@"
}

ensure_system_user() {
  local user="$1" home="$2"
  if ! id -u "$user" >/dev/null 2>&1; then
    useradd --system --home-dir "$home" --no-create-home --shell /usr/sbin/nologin --user-group "$user"
  fi
}

repo_root() { cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd; }

python_ok() {
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'
}

# /etc/ipf3 is shared by the server and the agent when both run on one host, so
# the directory itself stays world-traversable and each secret file carries its
# own owner/group/mode (server.env root:ipf3 0640, agent.json root:ipf3-agent 0640).
ensure_etc_dir() {
  install -d -m 0755 -o root -g root /etc/ipf3
  chown root:root /etc/ipf3
  chmod 0755 /etc/ipf3
}

# Fingerprint of the web UI sources. web/dist is committed prebuilt together with
# web/dist/BUILD_ID; when they match, servers need neither Node.js nor npm.
web_source_hash() {
  (cd "$1/web" && find src public index.html package.json package-lock.json vite.config.ts tailwind.config.js \
      postcss.config.js tsconfig.json -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)
}

prebuilt_web_ok() {
  [[ -f "$1/web/dist/index.html" && -f "$1/web/dist/BUILD_ID" ]] && [[ "$(cat "$1/web/dist/BUILD_ID")" == "$(web_source_hash "$1")" ]]
}

# Run ipf3-server as the service account with the production environment.
ipf3_cli() {
  runuser -u ipf3 -- bash -c 'set -a; . /etc/ipf3/server.env; set +a; exec /opt/ipf3/venv/bin/ipf3-server "$@"' ipf3-server "$@"
}
