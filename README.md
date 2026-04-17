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
- media source classification and local upload size guards
- caption parsing helpers for upcoming media delivery
- unit test coverage for the current behavior

Media delivery (`--photo`, `--file`, `--attach`) is not fully wired yet. The CLI currently rejects those modes with a clear error until the remaining implementation tasks are completed.

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
