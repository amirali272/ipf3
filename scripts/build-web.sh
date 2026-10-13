#!/usr/bin/env bash
# Build the web UI into web/dist and stamp it with the source fingerprint, so
# servers can install it without Node.js. Run after changing anything in web/
# and commit web/dist together with the change.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../deploy/lib.sh
source "$ROOT/deploy/lib.sh"
cd "$ROOT/web"
npm ci --no-audit --no-fund
npm run build
web_source_hash "$ROOT" > dist/BUILD_ID
echo "web/dist built ($(cat dist/BUILD_ID))"
