# notify-telegram-cli

CLI tool for sending Telegram notifications through a bot, designed for autonomous local agents.

## What It Does

- sends Markdown messages by default via Telegram Rich Messages (`sendRichMessage`, Bot API 10.1+) with native rendering of tables, formulas, headings, and lists — no escaping needed
- automatically degrades to plain text when the Bot API server does not support Rich Messages
- also supports legacy `--plain`, `--html`, and `--markdownv2` modes
- sends photos inline with `--photo`
- sends files as documents with `--file`
- supports `--attach`, `--photo-id`, `--file-id`, multi-send, and `--album`
- supports JSON input via `--json` and machine-readable results via `--json-output`
- supports richer agent JSON with `tags`, `links`, `event`, and `meta`
- supports `notify --doctor` for config, install, proxy, and Telegram API checks
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

One-command install from GitHub with `git`:

```bash
bash -lc 'set -euo pipefail; REPO="$HOME/.local/share/notify-telegram-cli/repo"; URL="https://github.com/ascorblack/notify-telegram-cli.git"; if [ -d "$REPO/.git" ]; then git -C "$REPO" pull --ff-only; else mkdir -p "$(dirname "$REPO")"; git clone "$URL" "$REPO"; fi; "$REPO/scripts/install-notify.sh"'
```

## Install Notify + Codex Skill

If you already cloned the repo locally:

```bash
./scripts/install-codex-skill.sh
```

One-command install from GitHub with `git`:

```bash
bash -lc 'set -euo pipefail; REPO="$HOME/.local/share/notify-telegram-cli/repo"; URL="https://github.com/ascorblack/notify-telegram-cli.git"; if [ -d "$REPO/.git" ]; then git -C "$REPO" pull --ff-only; else mkdir -p "$(dirname "$REPO")"; git clone "$URL" "$REPO"; fi; "$REPO/scripts/install-codex-skill.sh"'
```

This installs the skill into:

- `${CODEX_HOME:-~/.codex}/skills/notify-telegram`
- compatibility copy: `~/.agents/skills/notify-telegram`

## Install Notify + Claude CLI Skill

If you already cloned the repo locally:

```bash
./scripts/install-claude-skill.sh
```

One-command install from GitHub with `git`:

```bash
bash -lc 'set -euo pipefail; REPO="$HOME/.local/share/notify-telegram-cli/repo"; URL="https://github.com/ascorblack/notify-telegram-cli.git"; if [ -d "$REPO/.git" ]; then git -C "$REPO" pull --ff-only; else mkdir -p "$(dirname "$REPO")"; git clone "$URL" "$REPO"; fi; "$REPO/scripts/install-claude-skill.sh"'
```

This installs the skill into:

- `${CLAUDE_HOME:-~/.claude}/skills/notify-telegram`

## Agent Skill

The agent-facing skill source of truth lives at [SKILL.md](skills/notify-telegram/SKILL.md).

It teaches agents when to notify, when to prefer `--json`, and how to send text, photos, files, albums, and fallback links.

## Mini Prompt

Ready-to-copy bootstrap prompts live in [agent-self-setup.md](prompts/agent-self-setup.md).

If the repository stays private, make sure `git clone` already works in your environment via HTTPS credentials or SSH.

Short Codex version:

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using plain `git`, run `scripts/install-codex-skill.sh`, verify that `~/.local/bin/notify` exists, verify the skill exists under the local Codex skill directory, run `~/.local/bin/notify --doctor --json-output`, and show me `~/.local/bin/notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged.
```

## Local Usage

Examples:

```bash
notify "deploy finished"
notify "# Nightly report

| suite | passed | failed |
|-------|--------|--------|
| api   | 120    | 0      |
| web   | 98     | 2      |"
notify --plain "no formatting at all"
notify --html "<b>Deploy done</b>"
notify --json '{"title":"Deploy","message":"done"}'
notify --json '{"message":"done","tags":["nightly","success"],"links":["https://example.com/run/123"],"event":{"type":"deploy","name":"nightly","status":"success","id":"run-123"},"meta":{"branch":"main","services":["api","worker"]}}'
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
notify --doctor
notify --doctor --json-output
~/.local/bin/notify --doctor --json-output
```

## JSON Schema

Agent-friendly JSON fields:

- `message`
- `title`
- `tag` or `tags`
- `link` or `links`
- `quote`
- `caption`
- `fallback_link`
- `silent`
- `disable_web_preview`
- `album`
- `parse_mode`: `markdown` (default, rich Markdown), `html`, `markdownv2`, or `plain`
- `event`: string or object, for example `{"type":"deploy","name":"nightly","status":"success","id":"run-123"}`
- `meta`: object with arbitrary context, for example `{"branch":"main","services":["api","worker"]}`
- `media`: ordered array of items like `{"type":"photo|photo_id|file|file_id|attach","source":"..."}`

`event` and `meta` are rendered into the outgoing Telegram text so autonomous agents can send richer structured context without hand-formatting prose.

## Formatting Modes

The default mode is rich Markdown: the message goes through `sendRichMessage` (Bot API 10.1+), so Telegram natively renders tables, math formulas, headings, nested lists, block quotes, and collapsible details blocks. Agents can pass ordinary Markdown as-is; the per-message limit in this mode is about 16000 characters instead of 4096.

If the Bot API server does not support Rich Messages yet, the CLI automatically re-sends the message as plain text and reports `degraded_to_plain: true` in `--json-output`.

Legacy modes: `--plain` (no formatting), `--html`, `--markdownv2` (requires manual escaping). In legacy modes `title`, tags, links, `event`, and `meta` are escaped automatically.

`--dry-run` prints the planned API requests as JSON without sending anything and without requiring configured credentials.

## Doctor

`notify --doctor` checks:

- local config presence and parseability
- token/chat/proxy source resolution
- whether `notify` is on `PATH`
- Codex/Claude skill installation paths
- Telegram `getMe` and `getChat` reachability through the configured proxy

`ok` means there are no hard failures. `ready_to_send` is stricter and tells an agent whether token/chat configuration is present and Telegram delivery checks passed. On a fresh install without secrets, expect warnings and `ready_to_send: false`.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Run the CLI directly from the repo:

```bash
python3 notify_cli.py --help
```
