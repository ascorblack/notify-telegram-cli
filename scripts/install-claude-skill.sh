#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib/install-common.sh"

REPO_ROOT="$(ensure_repo_checkout)"
CLAUDE_HOME_DIR="${CLAUDE_HOME:-$HOME/.claude}"

install_launcher "$REPO_ROOT"
copy_skill_dir "$REPO_ROOT" "$CLAUDE_HOME_DIR/skills"

log "Installed Claude skill: $CLAUDE_HOME_DIR/skills/notify-telegram"
print_config_hint
if [[ ":$PATH:" != *":$NOTIFY_INSTALL_BIN_DIR:"* ]]; then
  log "Note: $NOTIFY_INSTALL_BIN_DIR is not currently in PATH."
  log "Run directly for now: $NOTIFY_INSTALL_BIN_DIR/notify --help"
  log "To add it permanently, add this to your shell profile:"
  log "  export PATH=\"$NOTIFY_INSTALL_BIN_DIR:\$PATH\""
fi
log "Restart Claude CLI to pick up the new skill if it is already running."
