# notify-telegram-cli

CLI tool for sending Telegram notifications through a bot, designed for autonomous local agents.

## Current Status

This repository is the source of truth for the `notify` CLI.

Implemented so far:

- plain text notifications
- `HTML` and `MarkdownV2` parse modes
- proxy-aware Telegram delivery through local Xray HTTP proxy
- long text chunking
- quote-file support for text notifications
- photo and document delivery with `--photo`, `--file`, and `--attach`
- explicit Telegram-hosted media delivery with `--photo-id` and `--file-id`
- explicit text input files with `--message-file` and `--caption-file`
- JSON input payloads through `--json`
- machine-readable result output through `--json-output`
- ordered multi-media delivery in one CLI call
- photo albums with `--album`
- media source classification and local upload size guards
- caption parsing, caption overflow follow-up messages, and stdin caption support
- fallback-link delivery for oversized uploads and media send failures
- retry and timeout controls for temporary transport failures
- unit test coverage for the current behavior

## Repository Layout

- `notify_cli.py` - main CLI implementation
- `tests/test_notify_cli.py` - unit tests

## Local Usage

The global launcher is expected at:

```bash
~/.local/bin/notify
```

It imports the code from this repository directory:

```bash
/home/dev/notify-telegram-cli
```

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

Use `config.example.json` in this repo as a template.

## Development

Run the test suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Run the CLI directly from the repo:

```bash
python3 notify_cli.py --help
```

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
notify --file file_id:ABC123... --caption "reuse Telegram-hosted file"
notify --json '{"message":"dry run","media":[{"type":"photo","source":"./shot.png"}]}' --dry-run --json-output
```

## GitHub Prep

`gh` is already available and authenticated in the current environment.

Typical next steps:

```bash
git init
git add .
git commit -m "Initial import of notify telegram cli"
gh repo create notify-telegram-cli --private --source=. --remote=origin --push
```

Switch `--private` to `--public` if needed.
