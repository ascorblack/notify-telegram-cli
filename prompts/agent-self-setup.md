Use this prompt with an agent when you want it to install `notify` or install `notify` plus the local Telegram skill for a specific CLI.

## Notify Only

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using plain `git`, run `scripts/install-notify.sh`, verify that `~/.local/bin/notify` exists, run `~/.local/bin/notify --doctor --json-output`, and show me `~/.local/bin/notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged. If doctor returns warnings about missing token or chat id on a fresh install, treat that as expected and report `ready_to_send: false`.
```

## Codex

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using plain `git`, run `scripts/install-codex-skill.sh`, verify that `~/.local/bin/notify` exists, verify the skill exists under the local Codex skill directory, run `~/.local/bin/notify --doctor --json-output`, and show me `~/.local/bin/notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged. If doctor returns warnings about missing token or chat id on a fresh install, treat that as expected and report `ready_to_send: false`.
```

## Claude CLI

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using plain `git`, run `scripts/install-claude-skill.sh`, verify that `~/.local/bin/notify` exists, verify the skill exists under the local Claude skill directory, run `~/.local/bin/notify --doctor --json-output`, and show me `~/.local/bin/notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged. If doctor returns warnings about missing token or chat id on a fresh install, treat that as expected and report `ready_to_send: false`.
```
