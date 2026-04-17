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
log "Restart Claude CLI to pick up the new skill if it is already running."
