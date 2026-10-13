#!/usr/bin/env bash
# Unknown Monitor — guided installer for Ubuntu 22.04 / 24.04.
#
#   sudo ./install.sh
# or, without cloning first:
#   bash <(curl -fsSL https://raw.githubusercontent.com/amirali272/ipf3/main/install.sh)
#
# Asks only what it needs (domain, administrator, ...) and runs the scripts in
# deploy/ with the right options. All output is logged to $LOG.
set -Eeuo pipefail

REPO_URL="${UM_REPO_URL:-https://github.com/amirali272/ipf3.git}"
REPO_BRANCH="${UM_BRANCH:-main}"
FALLBACK_BRANCH="claude/gracious-ramanujan-enb5r9"   # used until the code is merged into main
SRC_DIR="${UM_SRC_DIR:-/opt/unknown-monitor/src}"
LOG=/var/log/unknown-monitor-install.log

# ----------------------------------------------------------------------------- look & feel
if [[ -t 1 ]]; then
  B=$'\e[1m'; R=$'\e[0m'
  G=$'\e[38;5;42m'; G2=$'\e[38;5;35m'; GR=$'\e[38;5;245m'; W=$'\e[38;5;255m'; RED=$'\e[38;5;203m'; Y=$'\e[38;5;221m'
else
  B=""; R=""; G=""; G2=""; GR=""; W=""; RED=""; Y=""
fi

banner() {
  clear 2>/dev/null || true
  printf '\n'
  printf '%s' "$G"
  cat <<'ART'
   ██╗   ██╗███╗   ██╗██╗  ██╗███╗   ██╗ ██████╗ ██╗    ██╗███╗   ██╗
   ██║   ██║████╗  ██║██║ ██╔╝████╗  ██║██╔═══██╗██║    ██║████╗  ██║
   ██║   ██║██╔██╗ ██║█████╔╝ ██╔██╗ ██║██║   ██║██║ █╗ ██║██╔██╗ ██║
   ██║   ██║██║╚██╗██║██╔═██╗ ██║╚██╗██║██║   ██║██║███╗██║██║╚██╗██║
   ╚██████╔╝██║ ╚████║██║  ██╗██║ ╚████║╚██████╔╝╚███╔███╔╝██║ ╚████║
    ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝
ART
  printf '%s' "$R"
  printf '   %s%sM  O  N  I  T  O  R%s   %s·  Network monitoring & traffic analytics%s\n' "$B" "$W" "$R" "$GR" "$R"
  printf '   %s──────────────────────────────────────────────────────────────────%s\n\n' "$G2" "$R"
}

section() {
  printf '\n %s%s■%s %s%s%s\n' "$B" "$G" "$R" "$B" "$1" "$R"
  if [[ -n "${2:-}" ]]; then printf ' %s%s%s\n' "$GR" "$2" "$R"; fi
}
ok()      { printf '   %s✔%s %s\n' "$G" "$R" "$*"; }
note()    { printf '   %s%s%s\n' "$GR" "$*" "$R"; }
warn()    { printf '   %s!%s %s\n' "$Y" "$R" "$*"; }
fail()    { printf '\n   %s✖ %s%s\n' "$RED" "$*" "$R" >&2; exit 1; }

# All prompts read from the terminal so the script also works via curl | bash.
ask() { # ask VAR "Question" "default"
  local __var="$1" q="$2" def="${3:-}" ans
  if [[ -n "$def" ]]; then
    printf '   %s?%s %s %s[%s]%s: ' "$G" "$R" "$q" "$GR" "$def" "$R" >/dev/tty
  else
    printf '   %s?%s %s: ' "$G" "$R" "$q" >/dev/tty
  fi
  IFS= read -r ans </dev/tty || true
  ans="${ans#"${ans%%[![:space:]]*}"}"; ans="${ans%"${ans##*[![:space:]]}"}"
  printf -v "$__var" '%s' "${ans:-$def}"
}

ask_secret() { # ask_secret VAR "Question"
  local __var="$1" q="$2" ans
  printf '   %s?%s %s: ' "$G" "$R" "$q" >/dev/tty
  IFS= read -rs ans </dev/tty || true
  printf '\n' >/dev/tty
  printf -v "$__var" '%s' "$ans"
}

confirm() { # confirm "Question" default(y|n)
  local def="${2:-n}" ans hint="y/N"
  [[ "$def" == "y" ]] && hint="Y/n"
  printf '   %s?%s %s %s[%s]%s: ' "$G" "$R" "$1" "$GR" "$hint" "$R" >/dev/tty
  IFS= read -r ans </dev/tty || true
  ans="${ans:-$def}"
  [[ "$ans" =~ ^[YyGg] ]]
}

choose() { # choose VAR "option 1" "option 2" ... -> VAR = 1..n
  local __var="$1"; shift
  local i=1 ans
  for o in "$@"; do
    printf '   %s%s%d%s  %s\n' "$B" "$G" "$i" "$R" "$o" >/dev/tty
    i=$((i + 1))
  done
  while true; do
    printf '\n   %s?%s Select %s[1-%d]%s: ' "$G" "$R" "$GR" "$#" "$R" >/dev/tty
    IFS= read -r ans </dev/tty || true
    if [[ "$ans" =~ ^[0-9]+$ && "$ans" -ge 1 && "$ans" -le $# ]]; then
      printf -v "$__var" '%s' "$ans"
      return
    fi
  done
}

kill_tree() { # kill a process and all its descendants
  local p
  for p in $(pgrep -P "$1" 2>/dev/null); do kill_tree "$p"; done
  kill -TERM "$1" 2>/dev/null || true
}

# Runs a command with a spinner; output goes to $LOG. On failure, shows the log tail.
run_step() { # run_step "Label" cmd args...
  local label="$1"; shift
  printf '\n==== %s (%s)\n' "$label" "$(date -Is)" >>"$LOG"
  local from; from=$(wc -l <"$LOG")
  # Own process group, so Ctrl+C stops the whole step instead of leaving it running unseen.
  ( "$@" ) >>"$LOG" 2>&1 </dev/null &
  local pid=$! i=0 start=$SECONDS detail="" cols
  # shellcheck disable=SC2064
  trap "kill_tree $pid; printf '\n\n   Cancelled. Re-run the installer to continue (it is safe to re-run).\n'; exit 130" INT TERM
  local frames=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
  cols=$(tput cols 2>/dev/null || echo 100)
  if [[ -t 1 ]]; then
    while kill -0 "$pid" 2>/dev/null; do
      # Show the current sub-step ("==> ..." lines written by the deploy scripts).
      if (( i % 8 == 0 )); then
        detail=$( { tail -n +"$from" "$LOG" | grep -a '==>' | tail -n 1 | sed -e 's/\x1b\[[0-9;]*m//g' -e 's/^.*==> //'; } 2>/dev/null || true)
      fi
      local frame="${frames[i++ % ${#frames[@]}]}" text="$label${detail:+ - $detail} ($((SECONDS - start))s)"
      (( SECONDS - start > 60 )) && text+="  · details: tail -f $LOG"
      printf '\r\e[K   %s%s%s %s' "$G" "$frame" "$R" "${text:0:$((cols - 8))}"
      sleep 0.12
    done
  fi
  local rc=0
  wait "$pid" || rc=$?
  trap - INT TERM
  if [[ $rc -eq 0 ]]; then
    printf '\r\e[K   %s✔%s %s %s(%ss)%s\n' "$G" "$R" "$label" "$GR" "$((SECONDS - start))" "$R"
  else
    printf '\r\e[K   %s✖%s %s\n\n' "$RED" "$R" "$label"
    printf '%s   Last lines of %s:%s\n' "$GR" "$LOG" "$R"
    tail -n 25 "$LOG" | sed 's/^/     /'
    fail "Installation step failed. Fix the problem above and run the installer again (it is safe to re-run)."
  fi
}

# Never exit silently: report the command and line that failed.
trap 'rc=$?; printf "\n   \e[38;5;203m✖ Unexpected error (exit %s) at line %s: %s\e[0m\n   Log: %s\n" "$rc" "$LINENO" "$BASH_COMMAND" "$LOG" >&2' ERR

# ----------------------------------------------------------------------------- checks
[[ $EUID -eq 0 ]] || { echo "Please run as root:  sudo $0"; exit 1; }
[[ -r /etc/os-release ]] && . /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || { echo "Unknown Monitor supports Ubuntu 22.04 / 24.04 (found ${PRETTY_NAME:-unknown})."; exit 1; }
: >"$LOG" 2>/dev/null || LOG=/tmp/unknown-monitor-install.log
chmod 600 "$LOG"

# Locate (or fetch) the source tree.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo /nonexistent)"
if [[ -x "$SELF_DIR/deploy/install-server.sh" ]]; then
  REPO="$SELF_DIR"
else
  REPO="$SRC_DIR"
fi

banner
printf '   %sUbuntu %s%s  ·  %s%s%s  ·  log: %s%s\n' "$GR" "${VERSION_ID:-?}" "$R" "$GR" "$(hostname)" "$R" "$GR$LOG" "$R"

download_src() {
  export DEBIAN_FRONTEND=noninteractive
  command -v git >/dev/null || { apt-get update -q && apt-get install -y -q git ca-certificates; }
  mkdir -p "$(dirname "$SRC_DIR")"
  [[ -d "$SRC_DIR/.git" ]] || git clone -q "$REPO_URL" "$SRC_DIR"
  local b
  for b in "$REPO_BRANCH" "$FALLBACK_BRANCH"; do
    if git -C "$SRC_DIR" fetch -q origin "$b" 2>/dev/null && git -C "$SRC_DIR" checkout -q -B "$b" FETCH_HEAD \
       && [[ -x "$SRC_DIR/deploy/install-server.sh" ]]; then
      return 0
    fi
  done
  echo "installer files not found in $REPO_URL"
  return 1
}
if [[ "$REPO" == "$SRC_DIR" ]]; then
  # Running via curl: fetch (or update) the source tree so deploy/ matches this installer.
  run_step "Downloading Unknown Monitor" download_src
fi
VERSION="$(cat "$REPO/VERSION" 2>/dev/null || echo '?')"

# ----------------------------------------------------------------------------- helpers
detect_ip() {
  local ip
  ip=$(curl -4 -fsS --max-time 4 https://api.ipify.org 2>/dev/null || true)
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')
  echo "${ip:-}"
}

valid_password() {
  local p="$1" c=0
  [[ "$p" =~ [a-z] ]] && c=$((c + 1))
  [[ "$p" =~ [A-Z] ]] && c=$((c + 1))
  [[ "$p" =~ [0-9] ]] && c=$((c + 1))
  [[ "$p" =~ [^A-Za-z0-9] ]] && c=$((c + 1))
  [[ ${#p} -ge 12 && $c -ge 3 ]]
}

is_ip() { [[ "$1" =~ ^[0-9.]+$ || "$1" == *:* ]]; }

ask_panel() {
  section "Panel address" "The domain (or IP) you will open in the browser. Point an A record to this server for a free, automatic SSL certificate."
  local detected; detected="$(detect_ip)"
  while true; do
    ask DOMAIN "Domain or IP" "${detected}"
    DOMAIN="${DOMAIN#https://}"; DOMAIN="${DOMAIN#http://}"; DOMAIN="${DOMAIN%%/*}"; DOMAIN="${DOMAIN,,}"
    if [[ -z "$DOMAIN" || ! "$DOMAIN" =~ ^[a-z0-9.:-]+$ ]]; then warn "Please enter a valid domain name or IP address."; continue; fi
    if [[ "$DOMAIN" =~ (^|\.)example\.(com|net|org)$ ]]; then warn "That is only an example — enter your own domain."; continue; fi
    break
  done
  EMAIL=""
  if is_ip "$DOMAIN"; then
    note "An IP address gets a self-signed certificate (the browser will show a one-time warning)."
  else
    local resolved; resolved=$(getent ahostsv4 "$DOMAIN" 2>/dev/null | awk 'NR==1{print $1}')
    if [[ -z "$resolved" ]]; then
      warn "$DOMAIN does not resolve yet — a self-signed certificate will be used. Re-run later for Let's Encrypt."
    else
      if [[ -n "$detected" && "$resolved" != "$detected" ]]; then
        warn "$DOMAIN points to $resolved, but this server looks like $detected (fine if you use a proxy/CDN)."
      else
        ok "$DOMAIN → $resolved"
      fi
      ask EMAIL "Email for SSL expiry notices (optional)" ""
    fi
  fi

  section "Administrator account" "Used to sign in to the panel."
  while true; do
    ask ADMIN_USER "Username" "admin"
    [[ "$ADMIN_USER" =~ ^[A-Za-z0-9_.-]{3,64}$ ]] && break
    warn "3–64 characters: letters, digits, . _ -"
  done
  note "Password: at least 12 characters, with 3 of: lowercase, uppercase, digit, symbol."
  while true; do
    ask_secret ADMIN_PASS "Password"
    if ! valid_password "$ADMIN_PASS"; then warn "Password does not meet the rules above."; continue; fi
    ask_secret ADMIN_PASS2 "Repeat password"
    [[ "$ADMIN_PASS" == "$ADMIN_PASS2" ]] && break
    warn "Passwords do not match."
  done

  section "Preferences"
  local systz; systz=$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)
  while true; do
    ask TIMEZONE "Timezone for daily/monthly traffic totals" "${systz:-UTC}"
    [[ -f "/usr/share/zoneinfo/$TIMEZONE" ]] && break
    warn "Unknown timezone (examples: Asia/Tehran, Europe/Berlin, UTC)."
  done
  UFW=0
  if confirm "Enable the firewall (allow SSH, HTTP, HTTPS only)?" n; then UFW=1; fi
}

ask_agent_common() {
  while true; do
    ask AGENT_NAME "Name for this server" "$(hostname -s)"
    [[ "$AGENT_NAME" =~ ^[A-Za-z0-9_.@-]{1,128}$ ]] && break
    warn "Letters, digits and . _ @ - only."
  done
  XRAY=0
  if confirm "Use this server as a VPN node (install Xray-core)?" y; then XRAY=1; fi
  IPERF=0
  if confirm "Also run an iperf3 endpoint here (for speed tests from other servers)?" n; then IPERF=1; fi
}

fetch_ca() { # fetch_ca host -> writes /etc/ipf3/server-ca.pem after confirmation
  local host="$1" tmp fp
  tmp=$(mktemp)
  if ! echo | timeout 10 openssl s_client -connect "$host:443" -servername "$host" 2>/dev/null | openssl x509 >"$tmp" 2>/dev/null; then
    rm -f "$tmp"; fail "Could not read the certificate of $host:443."
  fi
  fp=$(openssl x509 -in "$tmp" -noout -fingerprint -sha256 | cut -d= -f2)
  warn "The panel uses a certificate that is not publicly trusted (self-signed)."
  note "SHA-256 fingerprint: $fp"
  note "Compare it with the fingerprint shown at the end of the panel installation."
  confirm "Trust this certificate?" n || { rm -f "$tmp"; fail "Aborted."; }
  install -d -m 0755 /etc/ipf3
  install -m 0644 "$tmp" /etc/ipf3/server-ca.pem
  rm -f "$tmp"
  CA_FILE=/etc/ipf3/server-ca.pem
}

summary_box() {
  printf '\n   %s┌────────────────────────────────────────────────────────────────┐%s\n' "$G2" "$R"
  while IFS= read -r line; do
    printf '   %s│%s  %-62s%s│%s\n' "$G2" "$R" "$line" "$G2" "$R"
  done
  printf '   %s└────────────────────────────────────────────────────────────────┘%s\n' "$G2" "$R"
}

install_panel() {
  local args=(--domain "$DOMAIN" --tls auto --admin-user "$ADMIN_USER" --timezone "$TIMEZONE")
  [[ -n "$EMAIL" ]] && args+=(--email "$EMAIL")
  [[ $UFW -eq 1 ]] && args+=(--ufw)
  run_step "Installing panel (PostgreSQL, API, web UI, nginx, SSL)" \
    env IPF3_ADMIN_PASSWORD="$ADMIN_PASS" IPF3_QUIET_SUMMARY=1 "$REPO/deploy/install-server.sh" "${args[@]}"
  # shellcheck disable=SC1091
  . /run/ipf3-install.result
  PANEL_URL="https://$DOMAIN"
}

install_agent() { # uses PANEL_URL, TOKEN, AGENT_NAME, IPERF, CA_FILE
  local args=(--server "$PANEL_URL" --token "$TOKEN" --name "$AGENT_NAME")
  [[ $IPERF -eq 1 ]] && args+=(--iperf3-server)
  [[ ${XRAY:-0} -eq 1 ]] && args+=(--xray)
  [[ -n "${CA_FILE:-}" ]] && args+=(--ca-file "$CA_FILE")
  [[ -f /etc/ipf3/agent.json ]] && args+=(--reenroll)
  run_step "Installing monitoring agent" "$REPO/deploy/install-agent.sh" "${args[@]}"
}

# ----------------------------------------------------------------------------- menu
section "What would you like to do?" "Version $VERSION"
printf '\n'
choose MODE \
  "Install panel + agent on this server  ${GR}(recommended for the first server)${R}" \
  "Install panel only" \
  "Add this server to an existing panel  ${GR}(agent)${R}" \
  "Upgrade an existing installation" \
  "Uninstall completely" \
  "Exit"

case "$MODE" in
  1|2)
    ask_panel
    if [[ "$MODE" == 1 ]]; then
      section "This server"
      ask_agent_common
    fi
    section "Ready to install"
    {
      echo "Panel        https://$DOMAIN"
      echo "SSL          $(is_ip "$DOMAIN" && echo "self-signed" || echo "Let's Encrypt (self-signed fallback)")"
      echo "Admin        $ADMIN_USER"
      echo "Timezone     $TIMEZONE"
      if [[ "$MODE" == 1 ]]; then
        extras=""
        [[ $XRAY -eq 1 ]] && extras+=" + VPN (Xray)"
        [[ $IPERF -eq 1 ]] && extras+=" + iperf3"
        echo "This server  $AGENT_NAME$extras"
      fi
    } | summary_box
    confirm "Start installation?" y || fail "Aborted."
    printf '\n'
    install_panel
    if [[ "$TLS_MODE" == "self-signed" ]]; then
      FP=$(openssl x509 -in "$CERT" -noout -fingerprint -sha256 | cut -d= -f2)
    fi
    if [[ "$MODE" == 1 ]]; then
      TOKEN=$(runuser -u ipf3 -- bash -c 'set -a; . /etc/ipf3/server.env; set +a; exec /opt/ipf3/venv/bin/ipf3-server create-enrollment-token --note "local agent" --ttl-hours 1' 2>>"$LOG")
      CA_FILE=""
      [[ "$TLS_MODE" == "self-signed" ]] && CA_FILE="$CERT"
      install_agent
    fi
    {
      echo "Unknown Monitor is ready."
      echo ""
      echo "Open       https://$DOMAIN"
      echo "Username   $ADMIN_USER"
      echo "Password   (the one you entered)"
      if [[ -n "${FP:-}" ]]; then
        echo ""; echo "Certificate fingerprint (SHA-256):"; echo "${FP:0:47}"; echo "${FP:48}"
      fi
      echo ""
      if [[ ${XRAY:-0} -eq 1 ]]; then
        echo "VPN: open VPN → Inbounds, add an inbound on this server"
        echo "     (port 443 is used by the panel here: pick e.g. 8443)."
        echo ""
      fi
      echo "Add more servers: run this installer on each server and"
      echo "choose \"Add this server to an existing panel\"."
      echo "Get a token in the panel: Servers → Enroll server."
    } | summary_box
    ;;
  3)
    section "Connect to your panel" "Create a token in the panel: Servers → Enroll server."
    while true; do
      ask PANEL_URL "Panel address (e.g. https://monitor.example.com)" ""
      [[ "$PANEL_URL" == http*://* ]] || PANEL_URL="https://$PANEL_URL"
      PANEL_URL="${PANEL_URL%/}"; PANEL_URL="${PANEL_URL/http:\/\//https://}"
      host="${PANEL_URL#https://}"; host="${host%%/*}"
      if curl -fsS --max-time 10 "$PANEL_URL/healthz" >/dev/null 2>&1; then ok "Panel reachable"; CA_FILE=""; break; fi
      if curl -kfsS --max-time 10 "$PANEL_URL/healthz" >/dev/null 2>&1; then fetch_ca "$host"; ok "Panel reachable"; break; fi
      warn "Cannot reach $PANEL_URL/healthz — check the address and that port 443 is open."
    done
    while true; do
      ask TOKEN "Enrollment token" ""
      [[ "$TOKEN" =~ ^ipf3e_[A-Za-z0-9_-]{20,}$ ]] && break
      warn "The token starts with ipf3e_ — copy it from Servers → Enroll server."
    done
    ask_agent_common
    printf '\n'
    install_agent
    {
      echo "This server is now reporting to $PANEL_URL"
      echo "Name       $AGENT_NAME"
      echo ""
      echo "It appears as Online in the panel within a few seconds."
      echo "Logs:      journalctl -u ipf3-agent -f"
    } | summary_box
    ;;
  4)
    section "Upgrade"
    if [[ -d "$REPO/.git" ]]; then
      run_step "Fetching the latest version" git -C "$REPO" pull --ff-only
      VERSION="$(cat "$REPO/VERSION" 2>/dev/null || echo '?')"
    fi
    found=0
    if [[ -f /etc/ipf3/server.env ]]; then found=1; run_step "Upgrading panel (backup is taken first)" "$REPO/deploy/upgrade-server.sh"; fi
    if [[ -f /etc/ipf3/agent.json ]]; then
      found=1
      run_step "Upgrading agent" "$REPO/deploy/upgrade-agent.sh"
      if [[ ! -x /usr/local/bin/xray ]]; then
        if confirm "Turn this server into a VPN node (install Xray-core)?" y; then
          run_step "Installing Xray-core" "$REPO/deploy/install-xray.sh"
          run_step "Restarting agent" systemctl restart ipf3-agent.service
        fi
      elif confirm "Update Xray-core to the latest release?" n; then
        run_step "Updating Xray-core" "$REPO/deploy/install-xray.sh"
      fi
    fi
    [[ $found -eq 1 ]] || fail "No existing installation found on this server."
    printf '\n'; ok "Upgraded to version $VERSION"
    ;;
  5)
    "$REPO/deploy/uninstall.sh"
    exit $?
    ;;
  *) exit 0 ;;
esac
printf '\n'
