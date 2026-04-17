#!/usr/bin/env bash
set -euo pipefail

NOTIFY_REPO_SLUG="${NOTIFY_REPO_SLUG:-ascorblack/notify-telegram-cli}"
NOTIFY_INSTALL_REPO_DIR="${NOTIFY_INSTALL_REPO_DIR:-$HOME/.local/share/notify-telegram-cli/repo}"
NOTIFY_INSTALL_BIN_DIR="${NOTIFY_INSTALL_BIN_DIR:-$HOME/.local/bin}"
NOTIFY_INSTALL_CONFIG_DIR="${NOTIFY_INSTALL_CONFIG_DIR:-$HOME/.config/notify-telegram-cli}"

log() {
  printf '%s\n' "$*"
}

fail() {
  printf 'notify installer: error: %s\n' "$*" >&2
  exit 1
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "required command not found: $1"
  fi
}

script_dir() {
  cd "$(dirname "${BASH_SOURCE[0]}")" && pwd
}

repo_root_from_script() {
  local root
  root="$(cd "$(script_dir)/../.." && pwd)"
  if [ -f "$root/notify_cli.py" ]; then
    printf '%s\n' "$root"
    return 0
  fi
  return 1
}

ensure_repo_checkout() {
  if repo_root_from_script >/dev/null 2>&1; then
    repo_root_from_script
    return 0
  fi

  require_command gh
  require_command git

  mkdir -p "$(dirname "$NOTIFY_INSTALL_REPO_DIR")"
  if [ -d "$NOTIFY_INSTALL_REPO_DIR/.git" ]; then
    git -C "$NOTIFY_INSTALL_REPO_DIR" pull --ff-only >/dev/null
  elif [ -e "$NOTIFY_INSTALL_REPO_DIR" ]; then
    fail "install repo dir exists but is not a git checkout: $NOTIFY_INSTALL_REPO_DIR"
  else
    gh repo clone "$NOTIFY_REPO_SLUG" "$NOTIFY_INSTALL_REPO_DIR" >/dev/null
  fi

  if [ ! -f "$NOTIFY_INSTALL_REPO_DIR/notify_cli.py" ]; then
    fail "unable to locate notify_cli.py in $NOTIFY_INSTALL_REPO_DIR"
  fi

  printf '%s\n' "$NOTIFY_INSTALL_REPO_DIR"
}

install_launcher() {
  local repo_root="$1"
  local launcher_path="$NOTIFY_INSTALL_BIN_DIR/notify"

  mkdir -p "$NOTIFY_INSTALL_BIN_DIR"
  cat >"$launcher_path" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec python3 "$repo_root/notify_cli.py" "\$@"
EOF
  chmod +x "$launcher_path"

  log "Installed launcher: $launcher_path"
}

copy_skill_dir() {
  local repo_root="$1"
  local destination_root="$2"
  local source_dir="$repo_root/skills/notify-telegram"

  if [ ! -f "$source_dir/SKILL.md" ]; then
    fail "skill source not found: $source_dir/SKILL.md"
  fi

  mkdir -p "$destination_root/notify-telegram"
  cp -R "$source_dir/." "$destination_root/notify-telegram/"
}

print_config_hint() {
  log "Config file location: $NOTIFY_INSTALL_CONFIG_DIR/config.json"
  if [ ! -f "$NOTIFY_INSTALL_CONFIG_DIR/config.json" ]; then
    log "Create it from config.example.json or use TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID."
  fi
}
