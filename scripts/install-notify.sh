#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib/install-common.sh"

REPO_ROOT="$(ensure_repo_checkout)"
install_launcher "$REPO_ROOT"
print_config_hint

if [[ ":$PATH:" != *":$NOTIFY_INSTALL_BIN_DIR:"* ]]; then
  log "Note: $NOTIFY_INSTALL_BIN_DIR is not currently in PATH."
fi
