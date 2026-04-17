Use this prompt with an agent when you want it to install `notify` or install `notify` plus the local Telegram skill for a specific CLI.

## Notify Only

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using plain `git`, run `scripts/install-notify.sh`, verify `command -v notify`, and show me `notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged.
```

## Codex

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using plain `git`, run `scripts/install-codex-skill.sh`, verify `command -v notify`, verify the skill exists under the local Codex skill directory, and show me `notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged.
```

## Claude CLI

```text
Clone or update the private repo `ascorblack/notify-telegram-cli` into `~/.local/share/notify-telegram-cli/repo` using plain `git`, run `scripts/install-claude-skill.sh`, verify `command -v notify`, verify the skill exists under the local Claude skill directory, and show me `notify --help`. Do not put secrets into the git repo. If `~/.config/notify-telegram-cli/config.json` already exists, leave it unchanged.
```
