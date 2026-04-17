---
name: notify-telegram
description: Use when an agent should proactively notify the user in Telegram about progress, results, failures, screenshots, logs, or artifacts from local autonomous work.
---

# Notify Telegram

Use `notify` when the user should hear about an important event without reading the full terminal session.

## When to Use

- Long-running work finished, failed, or needs attention.
- A build, deploy, or migration produced a short summary plus an artifact.
- A screenshot should be shown inline in Telegram.
- A report, log bundle, or other file should be attached.
- The agent wants a predictable machine-friendly interface and should prefer JSON input.

## Preferred Pattern

For agents, prefer `--json` input and `--json-output`.

```bash
notify --json '{
  "title": "Deploy finished",
  "message": "Production is healthy.",
  "tag": ["deploy", "success"],
  "media": [
    {"type": "photo", "source": "/tmp/deploy.png"}
  ]
}' --json-output
```

## Common Commands

Plain text:

```bash
notify "Nightly run finished"
```

Formatted text:

```bash
notify --html "<b>Deploy done</b>"
notify --markdownv2 "*escaped* body"
```

Photo inline:

```bash
notify --photo /tmp/screenshot.png --caption "UI after fix"
notify --photo-id AgACAgIA... --caption "Reuse Telegram-hosted photo"
```

File attachment:

```bash
notify --file /tmp/logs.zip --title "Incident logs"
notify --file-id BQACAgIA... --message-file summary.txt
```

Multiple attachments and albums:

```bash
notify --photo /tmp/a.png --file /tmp/b.txt --caption "batch start" "batch body"
notify --album --photo /tmp/1.png --photo /tmp/2.png --caption "release gallery"
```

Fallback when a local file may be too large:

```bash
notify --file /tmp/huge.tar --fallback-link "https://example.com/huge.tar"
```

## JSON Input Shape

Useful fields:

- `message`
- `title`
- `tag`
- `link`
- `quote`
- `caption`
- `fallback_link`
- `silent`
- `disable_web_preview`
- `album`
- `parse_mode`: `html` or `markdownv2`
- `media`: ordered array of items like `{"type":"photo|photo_id|file|file_id|attach","source":"..."}`

Examples:

```bash
notify --json @payload.json
cat payload.json | notify --json -
```

## Safety Notes

- Do not send secrets unless the user explicitly wants them in Telegram.
- Prefer summaries over raw dumps.
- For very large local files, use `--fallback-link`.
- If a screenshot should render inline, use `--photo`, not `--file`.
- If the caller needs machine-readable delivery status, add `--json-output`.
