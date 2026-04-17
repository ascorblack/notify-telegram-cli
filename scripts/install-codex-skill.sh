#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$SCRIPT_DIR/lib/install-common.sh"

REPO_ROOT="$(ensure_repo_checkout)"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
LEGACY_AGENTS_SKILL_DIR="${LEGACY_AGENTS_SKILL_DIR:-$HOME/.agents/skills}"

install_launcher "$REPO_ROOT"
copy_skill_dir "$REPO_ROOT" "$CODEX_HOME_DIR/skills"
copy_skill_dir "$REPO_ROOT" "$LEGACY_AGENTS_SKILL_DIR"

log "Installed Codex skill: $CODEX_HOME_DIR/skills/notify-telegram"
log "Installed compatibility skill copy: $LEGACY_AGENTS_SKILL_DIR/notify-telegram"
print_config_hint
log "Restart Codex to pick up the new skill if it is already running."
