# notify-telegram-cli

CLI tool for sending Telegram notifications through a bot, designed for autonomous local agents.

## What It Does

- sends plain text, `HTML`, and `MarkdownV2` messages
- sends photos inline with `--photo`
- sends files as documents with `--file`
- supports `--attach`, `--photo-id`, `--file-id`, multi-send, and `--album`
- supports JSON input via `--json` and machine-readable results via `--json-output`
- routes requests through the local Xray HTTP proxy by default

## Secrets

Do not store real bot credentials in this repository.

Supported secret sources:

1. Environment variables

```bash
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export TELEGRAM_PROXY_URL="http://127.0.0.1:10809"
```

2. Local config outside the repository

```bash
~/.config/notify-telegram-cli/config.json
```

Use [config.example.json](config.example.json) as a template.

## Install Notify Only

If you already cloned the repo locally:

```bash
./scripts/install-notify.sh
```

One-command install from GitHub with `gh`:

```bash
bash -lc 'set -euo pipefail; REPO="$HOME/.local/share/notify-telegram-cli/repo"; if [ -d "$REPO/.git" ]; then git -C "$REPO" pull --ff-only; else mkdir -p "$(dirname "$REPO")"; gh repo clone ascorblack/notify-telegram-cli "$REPO"; fi; "$REPO/scripts/install-notify.sh"'
```

## Install Notify + Codex Skill

If you already cloned the repo locally:

```bash
./scripts/install-codex-skill.sh
```

One-command install from GitHub with `gh`:

```bash
bash -lc 'set -euo pipefail; REPO="$HOME/.local/share/notify-telegram-cli/repo"; if [ -d "$REPO/.git" ]; then git -C "$REPO" pull --ff-only; else mkdir -p "$(dirname "$REPO")"; gh repo clone ascorblack/notify-telegram-cli "$REPO"; fi; "$REPO/scripts/install-codex-skill.sh"'
```

This installs the skill into:

- `${CODEX_HOME:-~/.codex}/skills/notify-telegram`
- compatibility copy: `~/.agents/skills/notify-telegram`

## Install Notify + Claude CLI Skill

If you already cloned the repo locally:

```bash
./scripts/install-claude-skill.sh
```

One-command install from GitHub with `gh`:

```bash
bash -lc 'set -euo pipefail; REPO="$HOME/.local/share/notify-telegram-cli/repo"; if [ -d "$REPO/.git" ]; then git -C "$REPO" pull --ff-only; else mkdir -p "$(dirname "$REPO")"; gh repo clone ascorblack/notify-telegram-cli "$REPO"; fi; "$REPO/scripts/install-claude-skill.sh"'
```

This installs the skill into:

- `${CLAUDE_HOME:-~/.claude}/skills/notify-telegram`

## Agent Skill

The agent-facing skill source of truth lives at [SKILL.md](skills/notify-telegram/SKILL.md).

It teaches agents when to notify, when to prefer `--json`, and how to send text, photos, files, albums, and fallback links.

## Mini Prompt

Ready-to-copy bootstrap prompts live in [agent-self-setup.md](prompts/agent-self-setup.md).

Short Codex version:

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using `gh`, run `scripts/install-codex-skill.sh`, verify `command -v notify`, verify the skill exists under the local Codex skill directory, and show me `notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged.
```

## Local Usage

Examples:

```bash
notify "deploy finished"
notify --html "<b>Deploy done</b>"
notify --json '{"title":"Deploy","message":"done"}'
notify --message-file summary.txt
notify --photo screenshot.png --caption "UI after fix"
notify --photo-id AgACAgIA... --caption-file caption.txt
notify --album --photo shot-1.png --photo shot-2.png --caption "release gallery"
notify --file logs.zip --title "Incident logs"
notify --file-id BQACAgIA... --message-file note.txt
notify --photo screenshot.png --file logs.zip --caption "batch start" "batch body"
notify --attach artifact.png --tag nightly --tag success
notify --file huge.tar --fallback-link https://example.com/huge.tar
notify --json '{"message":"dry run","media":[{"type":"photo","source":"./shot.png"}]}' --dry-run --json-output
```

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Run the CLI directly from the repo:

```bash
python3 notify_cli.py --help
```
