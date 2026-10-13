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

# Run ipf3-server as the service account with the production environment.
ipf3_cli() {
  runuser -u ipf3 -- bash -c 'set -a; . /etc/ipf3/server.env; set +a; exec /opt/ipf3/venv/bin/ipf3-server "$@"' ipf3-server "$@"
}
