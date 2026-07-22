#!/usr/bin/env python3
"""Telegram notify CLI."""

from __future__ import annotations

import argparse
import html as html_module
import mimetypes
import json
import os
import shutil
import sys
import time
from pathlib import Path
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_PROXY_URL = "http://127.0.0.1:10809"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_RETRY_COUNT = 2
FILE_ID_PREFIX = "file_id:"
PHOTO_MAX_BYTES = 10 * 1024 * 1024
DOCUMENT_MAX_BYTES = 50 * 1024 * 1024
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_RICH_MESSAGE_LIMIT = 16000
TELEGRAM_CAPTION_LIMIT = 1024
TELEGRAM_MEDIA_GROUP_LIMIT = 10
HTML_QUOTE_OPEN = "<pre><code>"
HTML_QUOTE_CLOSE = "</code></pre>"
PHOTO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
MEDIA_SIZE_LIMITS = {
    "photo": PHOTO_MAX_BYTES,
    "document": DOCUMENT_MAX_BYTES,
}


class NotifyError(Exception):
    """Raised when CLI usage or delivery fails."""


class MediaItemAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        media_items = list(getattr(namespace, "media_items", []) or [])
        media_items.append((self.dest, values))
        setattr(namespace, "media_items", media_items)
        setattr(namespace, self.dest, values)


class NotifyArgumentParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        parsed = super().parse_args(args, namespace)
        if getattr(parsed, "message_file", None) and getattr(parsed, "message_parts", None):
            self.error("message_parts are not allowed with --message-file")
        return parsed


RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


def get_default_config_path() -> Path:
    config_dir = os.environ.get("NOTIFY_INSTALL_CONFIG_DIR")
    if config_dir:
        return Path(config_dir) / "config.json"
    return Path.home() / ".config" / "notify-telegram-cli" / "config.json"


def load_local_config(config_path: Path | None = None) -> dict[str, object]:
    if config_path is None:
        config_path = get_default_config_path()
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise NotifyError(f"unable to read local config: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise NotifyError(f"local config is not valid JSON: {exc}") from exc


def resolve_runtime_settings(config_path: Path | None = None) -> tuple[str, str, str]:
    effective_config_path = config_path or get_default_config_path()
    config = load_local_config(config_path)
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or str(config.get("bot_token") or "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or str(config.get("chat_id") or "")
    proxy_url = os.environ.get("TELEGRAM_PROXY_URL") or str(config.get("proxy_url") or DEFAULT_PROXY_URL)

    if not token:
        raise NotifyError(
            "telegram bot token is not configured; set TELEGRAM_BOT_TOKEN or "
            f"{effective_config_path}"
        )
    if not chat_id:
        raise NotifyError(
            "telegram chat id is not configured; set TELEGRAM_CHAT_ID or "
            f"{effective_config_path}"
        )
    return token, chat_id, proxy_url


def build_parser() -> argparse.ArgumentParser:
    description = (
        "Send a Telegram message through your bot. By default the text is sent as "
        "Markdown via Telegram Rich Messages (sendRichMessage) with native "
        "rendering of tables, formulas, headings, and lists."
    )
    epilog = """Formatting modes:
  Default (--markdown):
    Rich Markdown via sendRichMessage. Write normal Markdown, no escaping
    needed. Telegram natively renders tables, math formulas, headings,
    nested lists, block quotes, and collapsible details blocks.
    Message limit is about 16000 characters per message.
    If the Bot API server does not support Rich Messages yet, the message
    is automatically re-sent as plain text.

  --plain:
    Plain text. Telegram will not parse formatting markup.

  --html:
    Legacy Telegram HTML parse mode. Common tags include:
      <b>bold</b>
      <i>italic</i>
      <u>underline</u>
      <s>strikethrough</s>
      <code>inline code</code>
      <pre>code block</pre>
      <a href="https://example.com">link</a>

  --markdownv2:
    Legacy Telegram MarkdownV2 parse mode. This is stricter and requires
    escaping special characters like: _ * [ ] ( ) ~ ` > # + - = | { } . !
    Prefer the default rich Markdown mode instead.

Input modes:
  notify "hello world"
  notify --html "<b>Deploy done</b>"
  notify --json '{"message":"hello from agent","title":"Deploy"}'
  notify --json '{"tags":["nightly"],"event":{"type":"deploy","status":"success"}}'
  cat payload.json | notify --json -
  printf 'line1\\nline2\\n' | notify -
  notify --message-file summary.txt
  notify --markdownv2 -
  notify --doctor --json-output
  notify - <<'EOF'
  first line
  second line
  EOF

Media modes:
  notify --photo screenshot.png --caption "UI after fix"
  notify --photo-id AgACAgIA... --caption-file caption.txt
  notify --album --photo shot-1.png --photo shot-2.png
  notify --file logs.zip --title "Incident logs"
  notify --file-id BQACAgIA... --message-file note.txt
  notify --attach artifact.png --tag nightly --tag success
  notify --file huge.tar --fallback-link https://example.com/huge.tar

Limits:
  Upload photo: 10 MB
  Upload document: 50 MB
  URL photo: 5 MB
  URL document: 20 MB

Proxy:
  Requests go through the local Xray HTTP proxy by default:
    http://127.0.0.1:10809
  Override with TELEGRAM_PROXY_URL if needed.
  Set TELEGRAM_PROXY_URL=none (or proxy_url "none" in config) to connect directly.

Environment overrides:
  TELEGRAM_BOT_TOKEN   Override bot token
  TELEGRAM_CHAT_ID     Override chat id
  TELEGRAM_PROXY_URL   Override proxy URL

Local config:
  ~/.config/notify-telegram-cli/config.json
"""
    parser = NotifyArgumentParser(
        prog="notify",
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--markdown",
        action="store_true",
        help="send message as rich Markdown via sendRichMessage (default)",
    )
    group.add_argument(
        "--plain",
        action="store_true",
        help="send message as plain text without any formatting",
    )
    group.add_argument("--html", action="store_true", help="send message with legacy Telegram HTML formatting")
    group.add_argument(
        "--markdownv2",
        action="store_true",
        help="send message with legacy Telegram MarkdownV2 formatting",
    )
    parser.set_defaults(media_items=[])
    parser.set_defaults(event=None, meta=None)
    parser.add_argument("--photo", metavar="SOURCE", action=MediaItemAction, help="send a photo source")
    parser.add_argument(
        "--photo-id",
        metavar="FILE_ID",
        action=MediaItemAction,
        help="send a Telegram-hosted photo by file_id",
    )
    parser.add_argument("--file", metavar="SOURCE", action=MediaItemAction, help="send a file source")
    parser.add_argument(
        "--file-id",
        metavar="FILE_ID",
        action=MediaItemAction,
        help="send a Telegram-hosted document by file_id",
    )
    parser.add_argument("--attach", metavar="SOURCE", action=MediaItemAction, help="auto-detect photo vs file")
    parser.add_argument("--album", action="store_true", help="send multiple photos as one Telegram album")
    parser.add_argument(
        "--disable-web-preview",
        action="store_true",
        help="disable link previews in Telegram",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="send message silently without notification sound",
    )
    parser.add_argument("--title", help="notification title")
    parser.add_argument("--tag", action="append", default=[], help="tag to include")
    parser.add_argument("--link", action="append", default=[], help="link to include")
    parser.add_argument("--fallback-link", help="link to send if media upload cannot be delivered")
    parser.add_argument("--quote", metavar="SOURCE", help="quote text from a local file")
    parser.add_argument("--json", metavar="SOURCE", help="read full notification spec from JSON, '-' for stdin, '@path' for file")
    parser.add_argument("--json-output", action="store_true", help="print machine-readable JSON result")
    parser.add_argument("--doctor", action="store_true", help="run self-checks for config, proxy, Telegram API, and installed skills")
    parser.add_argument("--dry-run", action="store_true", help="print the request without sending")
    parser.add_argument("--retries", type=int, default=DEFAULT_RETRY_COUNT, help="retry count for temporary network/API failures")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="request timeout in seconds")
    parser.add_argument(
        "--upload-timeout",
        type=int,
        default=None,
        help="timeout for media uploads in seconds; default scales with file size",
    )
    parser.add_argument("--message-file", metavar="PATH", help="read message body from a local file")
    caption_group = parser.add_mutually_exclusive_group()
    caption_group.add_argument("--caption", help="media caption text; pass '-' to read from stdin")
    caption_group.add_argument("--caption-file", metavar="PATH", help="read media caption from a local file")
    parser.add_argument(
        "message_parts",
        nargs="*",
        help='message text; pass "-" to read the full message from stdin',
    )
    return parser


def read_text_file(path: str, label: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise NotifyError(f"unable to read {label}: {exc}") from exc


def load_json_input(source: str, stdin) -> dict[str, object]:
    if source == "-":
        raw = stdin.read()
    elif source.startswith("@"):
        raw = read_text_file(source[1:], "json input file")
    else:
        raw = source
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotifyError(f"json input is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise NotifyError("json input must be a JSON object")
    return payload


def normalize_string_list(value: object, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    raise NotifyError(f"json input field '{field_name}' must be a string or list")


def normalize_boolean(value: object, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    raise NotifyError(
        f"json input field '{field_name}' must be a boolean or one of true/false/1/0/yes/no/on/off"
    )


def normalize_parse_mode(value: object) -> str:
    if value is None:
        return "markdown"
    if not isinstance(value, str):
        raise NotifyError("json input field 'parse_mode' must be a string or null")
    normalized = value.strip().lower()
    if normalized in {"", "markdown", "rich"}:
        return "markdown"
    if normalized in {"plain", "plaintext", "none"}:
        return "plain"
    if normalized == "html":
        return "html"
    if normalized == "markdownv2":
        return "markdownv2"
    raise NotifyError(
        "json input field 'parse_mode' must be one of markdown, html, markdownv2, plain, none"
    )


def resolve_mode(args: argparse.Namespace) -> str:
    if args.html:
        return "html"
    if args.markdownv2:
        return "markdownv2"
    if getattr(args, "plain", False):
        return "plain"
    return "markdown"


def message_limit_for_mode(mode: str) -> int:
    return TELEGRAM_RICH_MESSAGE_LIMIT if mode == "markdown" else TELEGRAM_MESSAGE_LIMIT


def normalize_event_payload(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {"name": value}
    if not isinstance(value, dict):
        raise NotifyError("json input field 'event' must be a string or object")
    normalized: dict[str, object] = {}
    for key, raw_value in value.items():
        if isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            normalized[str(key)] = raw_value
        elif isinstance(raw_value, list):
            normalized[str(key)] = [str(item) for item in raw_value]
        else:
            normalized[str(key)] = json.dumps(raw_value, ensure_ascii=False, sort_keys=True)
    return normalized


def normalize_meta_payload(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise NotifyError("json input field 'meta' must be an object")
    normalized: dict[str, object] = {}
    for key, raw_value in value.items():
        if isinstance(raw_value, list):
            normalized[str(key)] = [str(item) for item in raw_value]
        elif isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            normalized[str(key)] = raw_value
        else:
            normalized[str(key)] = json.dumps(raw_value, ensure_ascii=False, sort_keys=True)
    return normalized


def apply_json_input(args: argparse.Namespace, payload: dict[str, object]) -> argparse.Namespace:
    if "message" in payload and "message_parts" not in payload:
        message = payload["message"]
        args.message_parts = [message] if isinstance(message, str) else []
    if "title" in payload and isinstance(payload["title"], str):
        args.title = payload["title"]
    tags = normalize_string_list(payload.get("tag"), "tag")
    tags.extend(normalize_string_list(payload.get("tags"), "tags"))
    if tags:
        args.tag = tags
    links = normalize_string_list(payload.get("link"), "link")
    links.extend(normalize_string_list(payload.get("links"), "links"))
    if links:
        args.link = links
    if "quote" in payload and isinstance(payload["quote"], str):
        args.quote = payload["quote"]
    if "caption" in payload and isinstance(payload["caption"], str):
        args.caption = payload["caption"]
    if "fallback_link" in payload and isinstance(payload["fallback_link"], str):
        args.fallback_link = payload["fallback_link"]
    if "event" in payload:
        args.event = normalize_event_payload(payload["event"])
    if "meta" in payload:
        args.meta = normalize_meta_payload(payload["meta"])
    if "silent" in payload:
        args.silent = normalize_boolean(payload["silent"], "silent")
    if "disable_web_preview" in payload:
        args.disable_web_preview = normalize_boolean(
            payload["disable_web_preview"], "disable_web_preview"
        )
    if "album" in payload:
        args.album = normalize_boolean(payload["album"], "album")
    if "parse_mode" in payload:
        mode = normalize_parse_mode(payload["parse_mode"])
        args.html = mode == "html"
        args.markdownv2 = mode == "markdownv2"
        args.plain = mode == "plain"
        args.markdown = mode == "markdown"
    media_items = []
    if "media" in payload:
        media = payload["media"]
        if not isinstance(media, list):
            raise NotifyError("json input field 'media' must be a list")
        for item in media:
            if not isinstance(item, dict):
                raise NotifyError("json input field 'media' entries must be objects")
            media_type = item.get("type")
            source = item.get("source")
            if not isinstance(source, str) or not isinstance(media_type, str):
                raise NotifyError("json input media entries require string 'type' and 'source'")
            mapping = {
                "photo": "photo",
                "photo_id": "photo_id",
                "file": "file",
                "file_id": "file_id",
                "attach": "attach",
            }
            if media_type not in mapping:
                raise NotifyError(f"unsupported json media type: {media_type}")
            media_items.append((mapping[media_type], source))
    else:
        for key in ("photo", "photo_id", "file", "file_id", "attach"):
            value = payload.get(key)
            if isinstance(value, str):
                media_items.append((key, value))
    if media_items:
        args.media_items = media_items
        args.photo = args.photo_id = args.file = args.file_id = args.attach = None
        for kind, value in media_items:
            setattr(args, kind, value)
    return args


def validate_json_input_compatibility(args: argparse.Namespace) -> None:
    if not args.json:
        return
    if args.message_parts:
        raise NotifyError("--json cannot be combined with inline message text")
    if args.message_file:
        raise NotifyError("--json cannot be combined with --message-file")
    if args.quote:
        raise NotifyError("--json cannot be combined with --quote")
    if args.caption or args.caption_file:
        raise NotifyError("--json cannot be combined with caption flags")
    if args.media_items:
        raise NotifyError("--json cannot be combined with media flags")


def resolve_message(
    args: argparse.Namespace,
    stdin,
    stdin_is_tty: bool,
    required: bool = True,
    implicit_stdin: bool = True,
) -> str:
    if args.message_file:
        text = read_text_file(args.message_file, "message file")
    elif args.message_parts:
        if args.message_parts == ["-"] and not getattr(args, "json", None):
            text = stdin.read()
        else:
            text = " ".join(args.message_parts)
    elif implicit_stdin and not stdin_is_tty:
        text = stdin.read()
    elif not required:
        return ""
    else:
        raise NotifyError('message text is required; pass text or use "-" / stdin')

    if not text.strip():
        if not required:
            return ""
        raise NotifyError("message text is empty")
    return text


def format_metadata_value(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return "null"
    return str(value)


def build_event_block(event: dict[str, object] | None) -> str | None:
    if not event:
        return None
    lines: list[str] = []
    event_type = format_metadata_value(event["type"]) if "type" in event else ""
    event_name = format_metadata_value(event["name"]) if "name" in event else ""
    if event_type and event_name:
        lines.append(f"Event: {event_type} / {event_name}")
    elif event_name:
        lines.append(f"Event: {event_name}")
    elif event_type:
        lines.append(f"Event: {event_type}")
    field_labels = {
        "status": "Status",
        "phase": "Phase",
        "id": "ID",
        "summary": "Summary",
    }
    for key in ("status", "phase", "id", "summary"):
        if key in event and event[key] not in (None, ""):
            lines.append(f"{field_labels[key]}: {format_metadata_value(event[key])}")
    for key in event:
        if key in {"type", "name", "status", "phase", "id", "summary"}:
            continue
        lines.append(f"{key}: {format_metadata_value(event[key])}")
    return "\n".join(lines) if lines else None


def build_meta_block(meta: dict[str, object] | None) -> str | None:
    if not meta:
        return None
    lines = ["Meta:"]
    for key, value in meta.items():
        lines.append(f"{key}: {format_metadata_value(value)}")
    return "\n".join(lines)


def resolve_caption(
    args: argparse.Namespace,
    stdin,
    stdin_is_tty: bool,
    message_uses_stdin: bool = False,
) -> str | None:
    if getattr(args, "caption_file", None):
        caption = read_text_file(args.caption_file, "caption file")
    else:
        caption = args.caption
        if caption is None:
            return None
    if caption == "-" and not getattr(args, "json", None):
        if message_uses_stdin:
            raise NotifyError("caption stdin is ambiguous when message also reads from stdin")
        caption = stdin.read()
    if not caption.strip():
        raise NotifyError("caption text is empty")
    return caption


def format_title(title: str, mode: str) -> str:
    if mode == "html":
        return f"<b>{html_module.escape(title)}</b>"
    if mode == "markdownv2":
        return f"*{escape_markdown_v2(title)}*"
    if mode == "markdown":
        return f"**{title}**"
    return title


def build_text_body(
    args: argparse.Namespace,
    message_text: str,
    quote_text: str | None,
    mode: str = "plain",
) -> str:
    parts = []
    if args.title:
        parts.append(format_title(args.title, mode))
    event_text = build_event_block(getattr(args, "event", None))
    if event_text:
        parts.append(escape_for_mode(event_text, mode))
    if args.tag:
        parts.append(escape_for_mode(f"Tags: {', '.join(args.tag)}", mode))
    if args.link:
        parts.append(escape_for_mode(f"Links: {' '.join(args.link)}", mode))
    meta_text = build_meta_block(getattr(args, "meta", None))
    if meta_text:
        parts.append(escape_for_mode(meta_text, mode))
    if quote_text:
        parts.append(quote_text)
    parts.append(message_text)
    return "\n\n".join(parts)


def chunk_text_message(text: str, max_length: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    if max_length <= 0:
        raise ValueError("limit must be positive")
    if not text:
        return [""]

    def split_html_quote_blocks(source: str) -> list[tuple[bool, str]]:
        segments: list[tuple[bool, str]] = []
        index = 0
        while index < len(source):
            start = source.find(HTML_QUOTE_OPEN, index)
            if start == -1:
                if index < len(source):
                    segments.append((False, source[index:]))
                break
            if start > index:
                segments.append((False, source[index:start]))
            end = source.find(HTML_QUOTE_CLOSE, start)
            if end == -1:
                segments.append((False, source[start:]))
                break
            end += len(HTML_QUOTE_CLOSE)
            segments.append((True, source[start:end]))
            index = end
        return segments

    chunks: list[str] = []
    current = ""
    for atomic, segment in split_html_quote_blocks(text):
        pieces = [segment] if atomic else []
        if atomic:
            quote_inner = segment[len(HTML_QUOTE_OPEN) : -len(HTML_QUOTE_CLOSE)]
            quote_inner_limit = max_length - len(HTML_QUOTE_OPEN) - len(HTML_QUOTE_CLOSE)
            if quote_inner_limit <= 0:
                raise ValueError("limit too small for HTML quote block")
            pieces = [
                f"{HTML_QUOTE_OPEN}{quote_inner[index : index + quote_inner_limit]}{HTML_QUOTE_CLOSE}"
                for index in range(0, len(quote_inner), quote_inner_limit)
            ] or [f"{HTML_QUOTE_OPEN}{HTML_QUOTE_CLOSE}"]
        else:
            for line in segment.splitlines(keepends=True):
                if len(line) > max_length:
                    if current:
                        chunks.append(current)
                        current = ""
                    for index in range(0, len(line), max_length):
                        pieces.append(line[index : index + max_length])
                else:
                    pieces.append(line)

        for piece in pieces:
            if not piece:
                continue
            if current and len(current) + len(piece) > max_length:
                chunks.append(current)
                current = piece
            else:
                current += piece

    if current:
        chunks.append(current)
    return chunks or [""]


def chunk_caption_text(text: str, max_length: int = TELEGRAM_CAPTION_LIMIT) -> list[str]:
    if max_length <= 0:
        raise ValueError("limit must be positive")
    if not text:
        return [""]
    return [text[index : index + max_length] for index in range(0, len(text), max_length)] or [""]


MARKDOWN_V2_ESCAPES = {
    "\\": "\\\\",
    "_": "\\_",
    "*": "\\*",
    "[": "\\[",
    "]": "\\]",
    "(": "\\(",
    ")": "\\)",
    "~": "\\~",
    "`": "\\`",
    ">": "\\>",
    "#": "\\#",
    "+": "\\+",
    "-": "\\-",
    "=": "\\=",
    "|": "\\|",
    "{": "\\{",
    "}": "\\}",
    ".": "\\.",
    "!": "\\!",
}


def escape_markdown_v2(text: str) -> str:
    return "".join(MARKDOWN_V2_ESCAPES.get(char, char) for char in text)


def escape_for_mode(text: str, mode: str) -> str:
    if mode == "html":
        return html_module.escape(text)
    if mode == "markdownv2":
        return escape_markdown_v2(text)
    return text


def format_quote_block(text: str, mode: str = "plain") -> str:
    if mode in {"HTML", "html"} or mode is True:
        return f"{HTML_QUOTE_OPEN}{html_module.escape(text)}{HTML_QUOTE_CLOSE}"
    if mode in {"MarkdownV2", "markdownv2"}:
        return "\n".join(f"> {escape_markdown_v2(line)}" if line else ">" for line in text.splitlines())
    if mode == "markdown":
        return f"```\n{text}\n```"
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def classify_media_source(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        suffix = Path(parsed.path).suffix.lower()
    else:
        suffix = Path(source).suffix.lower()
    if suffix in PHOTO_EXTENSIONS:
        return "photo"
    return "document"


def looks_like_telegram_file_id(source: str) -> bool:
    return source.startswith(FILE_ID_PREFIX)


def normalize_media_source(source: str) -> str:
    if source.startswith(FILE_ID_PREFIX):
        return source[len(FILE_ID_PREFIX) :]
    return source


def resolve_media_inputs(args: argparse.Namespace) -> list[dict[str, str]]:
    media_inputs: list[dict[str, str]] = []
    for kind, value in getattr(args, "media_items", []) or []:
        if kind == "photo":
            media_inputs.append({"source": value, "media_kind": "photo"})
        elif kind == "photo_id":
            media_inputs.append({"source": f"{FILE_ID_PREFIX}{value}", "media_kind": "photo"})
        elif kind == "file":
            media_inputs.append({"source": value, "media_kind": "document"})
        elif kind == "file_id":
            media_inputs.append({"source": f"{FILE_ID_PREFIX}{value}", "media_kind": "document"})
        elif kind == "attach":
            media_inputs.append({"source": value, "media_kind": classify_media_source(value)})
        else:
            raise NotifyError(f"unsupported media input kind: {kind}")
    return media_inputs


def ensure_local_media_path_exists(source: str, path_exists) -> None:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return
    normalized_source = normalize_media_source(source)
    if path_exists(normalized_source):
        return
    if looks_like_telegram_file_id(source):
        return
    raise NotifyError(f"local media path does not exist: {source}")


def ensure_local_media_size(source: str, media_kind: str, stat_fn=os.stat) -> None:
    if media_kind not in MEDIA_SIZE_LIMITS:
        raise NotifyError(f"unsupported media kind: {media_kind}")

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return

    max_bytes = MEDIA_SIZE_LIMITS[media_kind]
    size = stat_fn(source).st_size
    if size > max_bytes:
        limit_mb = 10 if media_kind == "photo" else 50
        raise NotifyError(f"{media_kind} upload exceeds {limit_mb} MB limit")


def build_payload(
    chat_id: str,
    args: argparse.Namespace,
    text: str,
    mode: str | None = None,
) -> dict[str, object]:
    mode = resolve_mode(args) if mode is None else mode
    payload: dict[str, object] = {"chat_id": chat_id}
    if mode == "markdown":
        payload["rich_message"] = {"markdown": text}
    else:
        payload["text"] = text
        if mode == "html":
            payload["parse_mode"] = "HTML"
        elif mode == "markdownv2":
            payload["parse_mode"] = "MarkdownV2"
    if args.disable_web_preview:
        payload["link_preview_options"] = {"is_disabled": True}
    if args.silent:
        payload["disable_notification"] = True
    return payload


def text_send_method_for_mode(mode: str) -> str:
    return "sendRichMessage" if mode == "markdown" else "sendMessage"


def is_rich_unsupported_error(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 404
    if isinstance(exc, NotifyError):
        description = str(exc).lower()
        return "method not found" in description or "unknown method" in description
    return False


def build_http_opener(proxy_url: str):
    if not proxy_url or proxy_url.strip().lower() in {"none", "direct"}:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    return urllib.request.build_opener(proxy_handler)


def build_json_request(token: str, method: str, payload: dict[str, object]) -> urllib.request.Request:
    return urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def parse_telegram_response(raw_body: bytes) -> dict[str, object]:
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NotifyError(f"Telegram API returned invalid JSON: {raw_body!r}") from exc

    if not body.get("ok"):
        description = body.get("description", "unknown Telegram API error")
        raise NotifyError(f"Telegram API error: {description}")
    return body


def call_telegram_json_method(
    token: str,
    method: str,
    payload: dict[str, object],
    opener,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRY_COUNT,
):
    request = build_json_request(token, method, payload)
    with open_with_retry(opener, request, timeout=timeout, retries=retries) as response:
        raw_body = response.read()
    return parse_telegram_response(raw_body)


def is_retryable_http_error(exc: urllib.error.HTTPError) -> bool:
    return exc.code in RETRYABLE_HTTP_STATUS_CODES


def compute_retry_delay(exc: Exception, attempt_index: int) -> float:
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = None
        if getattr(exc, "headers", None):
            retry_after = exc.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 30.0))
            except ValueError:
                pass
    return min(0.25 * (2**attempt_index), 2.0)


def open_with_retry(opener, request, timeout: int, retries: int):
    attempts_remaining = max(0, retries)
    attempt_index = 0
    while True:
        try:
            return opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            if attempts_remaining <= 0 or not is_retryable_http_error(exc):
                raise
            time.sleep(compute_retry_delay(exc, attempt_index))
            attempts_remaining -= 1
            attempt_index += 1
        except urllib.error.URLError as exc:
            if attempts_remaining <= 0:
                raise
            time.sleep(compute_retry_delay(exc, attempt_index))
            attempts_remaining -= 1
            attempt_index += 1


def normalize_multipart_field_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_multipart_request(
    token: str,
    method: str,
    fields: dict[str, object],
    files: dict[str, object],
) -> urllib.request.Request:
    boundary = f"----notifycli{uuid.uuid4().hex}"
    body = bytearray()

    def append_line(line: str = "") -> None:
        body.extend(line.encode("utf-8"))
        body.extend(b"\r\n")

    for name, value in fields.items():
        append_line(f"--{boundary}")
        append_line(f'Content-Disposition: form-data; name="{name}"')
        append_line()
        append_line(normalize_multipart_field_value(value))

    for name, source in files.items():
        if isinstance(source, tuple):
            filename, file_bytes, content_type = source
            content = bytes(file_bytes)
        else:
            path = Path(source)
            filename = path.name
            content = path.read_bytes()
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"

        append_line(f"--{boundary}")
        append_line(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"')
        append_line(f"Content-Type: {content_type}")
        append_line()
        body.extend(content)
        body.extend(b"\r\n")

    append_line(f"--{boundary}--")

    return urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )


def send_message(
    token: str,
    payload: dict[str, object],
    opener,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRY_COUNT,
):
    return call_telegram_json_method(
        token,
        "sendMessage",
        payload,
        opener,
        timeout=timeout,
        retries=retries,
    )


def send_text_body(
    token: str,
    chat_id: str,
    args: argparse.Namespace,
    mode: str,
    text: str,
    opener,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRY_COUNT,
) -> dict[str, object]:
    """Send text in mode-sized chunks; degrade rich mode to plain when unsupported."""
    chunks = chunk_text_message(text, max_length=message_limit_for_mode(mode))
    method = text_send_method_for_mode(mode)
    chunks_sent = 0
    degraded = False
    for chunk in chunks:
        try:
            call_telegram_json_method(
                token,
                method,
                build_payload(chat_id, args, chunk, mode),
                opener,
                timeout=timeout,
                retries=retries,
            )
        except (NotifyError, urllib.error.HTTPError) as exc:
            if mode != "markdown" or chunks_sent > 0 or not is_rich_unsupported_error(exc):
                raise
            degraded = True
            break
        chunks_sent += 1

    if degraded:
        method = "sendMessage"
        chunks_sent = 0
        for chunk in chunk_text_message(text, max_length=TELEGRAM_MESSAGE_LIMIT):
            call_telegram_json_method(
                token,
                method,
                build_payload(chat_id, args, chunk, "plain"),
                opener,
                timeout=timeout,
                retries=retries,
            )
            chunks_sent += 1

    return {"method": method, "chunks_sent": chunks_sent, "degraded_to_plain": degraded}


def emit_result(stdout, as_json: bool, payload: dict[str, object]) -> None:
    if as_json:
        stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def build_fallback_text(text: str, fallback_link: str, caption_text: str | None = None) -> str:
    parts = []
    if caption_text and caption_text.strip():
        parts.append(caption_text)
    if text.strip():
        parts.append(text)
    parts.append(fallback_link)
    return "\n\n".join(parts)


def build_media_payload(
    chat_id: str,
    args: argparse.Namespace,
    caption: str | None,
    mode: str | None = None,
) -> dict[str, object]:
    mode = resolve_mode(args) if mode is None else mode
    payload: dict[str, object] = {"chat_id": chat_id}
    if caption:
        payload["caption"] = caption
        if mode == "html":
            payload["parse_mode"] = "HTML"
        elif mode == "markdownv2":
            payload["parse_mode"] = "MarkdownV2"
    if args.silent:
        payload["disable_notification"] = True
    return payload


def local_media_size(source: str, path_exists, stat_fn) -> int:
    normalized = normalize_media_source(source)
    parsed = urlparse(normalized)
    if parsed.scheme in {"http", "https"} or not path_exists(normalized):
        return 0
    try:
        return stat_fn(normalized).st_size
    except OSError:
        return 0


def build_media_requests_preview(
    args: argparse.Namespace,
    mode: str,
    media_inputs: list[dict[str, str]],
    primary_caption: str | None,
    followup_text: str,
) -> list[dict[str, object]]:
    requests: list[dict[str, object]] = []
    if args.album:
        media = []
        for index, item in enumerate(media_inputs):
            entry: dict[str, object] = {"type": "photo", "media": normalize_media_source(item["source"])}
            if index == 0 and primary_caption:
                entry["caption"] = primary_caption
            media.append(entry)
        requests.append(
            {"method": "sendMediaGroup", "payload": {"chat_id": "<chat_id>", "media": media}}
        )
    else:
        for index, item in enumerate(media_inputs):
            media_kind = item["media_kind"]
            payload = build_media_payload(
                "<chat_id>", args, primary_caption if index == 0 else None, mode
            )
            payload["photo" if media_kind == "photo" else "document"] = normalize_media_source(item["source"])
            requests.append(
                {
                    "method": "sendPhoto" if media_kind == "photo" else "sendDocument",
                    "payload": payload,
                }
            )
    if followup_text:
        for chunk in chunk_text_message(followup_text, max_length=message_limit_for_mode(mode)):
            requests.append(
                {
                    "method": text_send_method_for_mode(mode),
                    "payload": build_payload("<chat_id>", args, chunk, mode),
                }
            )
    return requests


def compute_upload_timeout(args: argparse.Namespace, size_bytes: int) -> int:
    if getattr(args, "upload_timeout", None):
        return args.upload_timeout
    # assume at least ~64 KiB/s through the proxy plus base timeout headroom
    return max(args.timeout, 30 + size_bytes // (64 * 1024))


def send_media(
    token: str,
    method: str,
    source_field: str,
    source: str,
    payload: dict[str, object],
    opener,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRY_COUNT,
    path_exists=None,
):
    path_exists = Path.exists if path_exists is None else path_exists
    source = normalize_media_source(source)
    parsed = urlparse(source)
    is_remote = parsed.scheme in {"http", "https"}
    is_local_path = not is_remote and path_exists(Path(source))

    if is_local_path:
        request = build_multipart_request(token, method, payload, {source_field: source})
    else:
        request_payload = dict(payload)
        request_payload[source_field] = source
        request = build_json_request(token, method, request_payload)

    with open_with_retry(opener, request, timeout=timeout, retries=retries) as response:
        raw_body = response.read()
    return parse_telegram_response(raw_body)


def build_media_group_request(
    token: str,
    chat_id: str,
    args: argparse.Namespace,
    media_sources: list[str],
    caption: str | None,
    path_exists=None,
) -> urllib.request.Request:
    path_exists = Path.exists if path_exists is None else path_exists
    media: list[dict[str, object]] = []
    files: dict[str, object] = {}

    for index, source in enumerate(media_sources):
        normalized = normalize_media_source(source)
        parsed = urlparse(normalized)
        is_remote = parsed.scheme in {"http", "https"}
        is_local_path = not is_remote and path_exists(Path(normalized))
        media_value = normalized
        if is_local_path:
            attachment_name = f"file{index}"
            media_value = f"attach://{attachment_name}"
            files[attachment_name] = normalized

        item: dict[str, object] = {"type": "photo", "media": media_value}
        if index == 0 and caption:
            item["caption"] = caption
            if args.html:
                item["parse_mode"] = "HTML"
            elif args.markdownv2:
                item["parse_mode"] = "MarkdownV2"
        media.append(item)

    fields: dict[str, object] = {"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)}
    if args.silent:
        fields["disable_notification"] = True
    return build_multipart_request(token, "sendMediaGroup", fields, files)


def send_media_group(
    token: str,
    chat_id: str,
    args: argparse.Namespace,
    media_sources: list[str],
    caption: str | None,
    opener,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    retries: int = DEFAULT_RETRY_COUNT,
    path_exists=None,
):
    request = build_media_group_request(token, chat_id, args, media_sources, caption, path_exists=path_exists)
    with open_with_retry(opener, request, timeout=timeout, retries=retries) as response:
        raw_body = response.read()
    return parse_telegram_response(raw_body)


def inspect_runtime_settings(config_path: Path | None = None) -> dict[str, object]:
    if config_path is None:
        config_path = get_default_config_path()
    result: dict[str, object] = {
        "config_path": str(config_path),
        "config_exists": config_path.exists(),
        "config_error": None,
        "token": "",
        "token_source": None,
        "chat_id": "",
        "chat_id_source": None,
        "proxy_url": DEFAULT_PROXY_URL,
        "proxy_source": "default",
    }
    try:
        config = load_local_config(config_path)
    except NotifyError as exc:
        result["config_error"] = str(exc)
        config = {}

    env_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    env_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    env_proxy = os.environ.get("TELEGRAM_PROXY_URL")
    config_token = str(config.get("bot_token") or "")
    config_chat_id = str(config.get("chat_id") or "")
    config_proxy = str(config.get("proxy_url") or "")

    if env_token:
        result["token"] = env_token
        result["token_source"] = "env"
    elif config_token:
        result["token"] = config_token
        result["token_source"] = "config"

    if env_chat_id:
        result["chat_id"] = env_chat_id
        result["chat_id_source"] = "env"
    elif config_chat_id:
        result["chat_id"] = config_chat_id
        result["chat_id_source"] = "config"

    if env_proxy:
        result["proxy_url"] = env_proxy
        result["proxy_source"] = "env"
    elif config_proxy:
        result["proxy_url"] = config_proxy
        result["proxy_source"] = "config"

    return result


def get_expected_launcher_path() -> Path:
    bin_dir = os.environ.get("NOTIFY_INSTALL_BIN_DIR")
    if bin_dir:
        return Path(bin_dir) / "notify"
    return Path.home() / ".local" / "bin" / "notify"


def get_skill_paths() -> dict[str, Path]:
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    agents_skill_root = Path(os.environ.get("LEGACY_AGENTS_SKILL_DIR") or (Path.home() / ".agents" / "skills"))
    claude_home = Path(os.environ.get("CLAUDE_HOME") or (Path.home() / ".claude"))
    return {
        "codex_skill": codex_home / "skills" / "notify-telegram" / "SKILL.md",
        "agents_skill": agents_skill_root / "notify-telegram" / "SKILL.md",
        "claude_skill": claude_home / "skills" / "notify-telegram" / "SKILL.md",
    }


def format_check_line(status: str, name: str, message: str) -> str:
    return f"[{status}] {name}: {message}"


def run_doctor(
    stdout,
    stderr,
    as_json: bool,
    opener_factory,
    timeout: int,
    retries: int,
    program_path: str | None = None,
) -> int:
    checks: list[dict[str, object]] = []
    runtime = inspect_runtime_settings()

    def add_check(name: str, status: str, message: str) -> None:
        checks.append({"name": name, "status": status, "message": message})

    if runtime["config_error"]:
        add_check("config", "fail", str(runtime["config_error"]))
    elif runtime["config_exists"]:
        add_check("config", "ok", f"loaded {runtime['config_path']}")
    else:
        add_check("config", "warn", f"not found at {runtime['config_path']}")

    if runtime["token"]:
        add_check("token", "ok", f"configured via {runtime['token_source']}")
    else:
        add_check("token", "warn", "missing TELEGRAM_BOT_TOKEN or config bot_token")

    if runtime["chat_id"]:
        add_check("chat_id", "ok", f"configured via {runtime['chat_id_source']}")
    else:
        add_check("chat_id", "warn", "missing TELEGRAM_CHAT_ID or config chat_id")

    add_check("proxy", "ok", f"{runtime['proxy_url']} via {runtime['proxy_source']}")

    expected_launcher_path = get_expected_launcher_path()
    launcher_on_path = shutil.which("notify")
    invoked_launcher_path = None
    raw_program_path = os.environ.get("NOTIFY_LAUNCHER_PATH") or program_path
    if raw_program_path:
        candidate = Path(raw_program_path)
        try:
            if candidate.exists() and candidate.name == "notify":
                invoked_launcher_path = candidate.resolve()
        except OSError:
            invoked_launcher_path = None
    if expected_launcher_path.exists():
        if invoked_launcher_path and invoked_launcher_path == expected_launcher_path.resolve():
            add_check("launcher", "ok", str(expected_launcher_path))
        elif launcher_on_path and Path(launcher_on_path).resolve() == expected_launcher_path.resolve():
            add_check("launcher", "ok", str(expected_launcher_path))
        elif launcher_on_path:
            add_check(
                "launcher",
                "warn",
                f"installed at {expected_launcher_path}, but PATH resolves notify to {launcher_on_path}",
            )
        else:
            add_check(
                "launcher",
                "warn",
                f"installed at {expected_launcher_path}, but it is not currently on PATH",
            )
    else:
        add_check("launcher", "warn", f"expected launcher not found at {expected_launcher_path}")

    skill_paths = get_skill_paths()
    for name, path in skill_paths.items():
        if path.exists():
            add_check(name, "ok", str(path))
        else:
            add_check(name, "warn", f"not found at {path}")

    token = str(runtime["token"])
    chat_id = str(runtime["chat_id"])
    if token and chat_id:
        try:
            opener = opener_factory(str(runtime["proxy_url"]))
            get_me = call_telegram_json_method(
                token,
                "getMe",
                {},
                opener,
                timeout=timeout,
                retries=retries,
            )
            bot_username = get_me.get("result", {}).get("username", "<unknown>")
            add_check("telegram_getMe", "ok", f"reachable as @{bot_username}")

            get_chat = call_telegram_json_method(
                token,
                "getChat",
                {"chat_id": chat_id},
                opener,
                timeout=timeout,
                retries=retries,
            )
            chat_type = get_chat.get("result", {}).get("type", "<unknown>")
            add_check("telegram_getChat", "ok", f"chat {chat_id} reachable ({chat_type})")
        except (NotifyError, urllib.error.HTTPError, urllib.error.URLError) as exc:
            add_check("telegram", "fail", str(exc))

    failed = any(check["status"] == "fail" for check in checks)
    ready_to_send = bool(runtime["token"] and runtime["chat_id"])
    if ready_to_send:
        ready_to_send = not any(check["name"] == "telegram" and check["status"] == "fail" for check in checks)
        ready_to_send = ready_to_send and any(
            check["name"] == "telegram_getChat" and check["status"] == "ok" for check in checks
        )
    result = {
        "ok": not failed,
        "ready_to_send": ready_to_send,
        "command": "doctor",
        "checks": checks,
        "runtime": {
            "config_path": runtime["config_path"],
            "config_exists": runtime["config_exists"],
            "token_source": runtime["token_source"],
            "chat_id_source": runtime["chat_id_source"],
            "proxy_source": runtime["proxy_source"],
            "proxy_url": runtime["proxy_url"],
        },
    }

    if as_json:
        stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    else:
        for check in checks:
            stdout.write(format_check_line(check["status"], check["name"], check["message"]) + "\n")

    for check in checks:
        if check["status"] == "fail":
            stderr.write(format_check_line(check["status"], check["name"], check["message"]) + "\n")

    return 1 if failed else 0


def validate_doctor_args(args: argparse.Namespace) -> None:
    if not args.doctor:
        return
    if args.json:
        raise NotifyError("--doctor cannot be combined with --json")
    if args.message_parts:
        raise NotifyError("--doctor cannot be combined with message text")
    if args.message_file:
        raise NotifyError("--doctor cannot be combined with --message-file")
    if args.caption or args.caption_file:
        raise NotifyError("--doctor cannot be combined with caption flags")
    if args.media_items:
        raise NotifyError("--doctor cannot be combined with media flags")
    if args.title or args.tag or args.link:
        raise NotifyError("--doctor cannot be combined with title, tag, or link flags")
    if args.fallback_link or args.quote:
        raise NotifyError("--doctor cannot be combined with fallback or quote flags")
    if (
        args.html
        or args.markdownv2
        or args.markdown
        or args.plain
        or args.album
        or args.silent
        or args.disable_web_preview
    ):
        raise NotifyError("--doctor cannot be combined with formatting or delivery flags")
    if args.dry_run:
        raise NotifyError("--doctor cannot be combined with --dry-run")


def main(
    argv=None,
    stdin=None,
    stdout=None,
    stderr=None,
    stdin_is_tty=None,
    opener_factory=None,
    path_exists=None,
    stat_fn=None,
) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    if stdin_is_tty is None:
        stdin_is_tty = stdin.isatty()
    if opener_factory is None:
        opener_factory = build_http_opener
    if path_exists is None:
        path_exists = lambda path: Path(path).exists()
    if stat_fn is None:
        stat_fn = os.stat

    parser = build_parser()

    try:
        args = parser.parse_args(argv)
        validate_doctor_args(args)
        if args.doctor:
            return run_doctor(
                stdout,
                stderr,
                args.json_output,
                opener_factory=opener_factory,
                timeout=args.timeout,
                retries=args.retries,
                program_path=sys.argv[0],
            )
        validate_json_input_compatibility(args)
        if args.json:
            args = apply_json_input(args, load_json_input(args.json, stdin))
        media_inputs = resolve_media_inputs(args)
        media_source = media_inputs[0]["source"] if media_inputs else None
        message_uses_stdin = (not args.json) and (
            args.message_parts == ["-"] or (
            not args.message_parts
            and not args.message_file
            and not stdin_is_tty
            and not (media_source and args.caption == "-")
            )
        )
        caption_text = resolve_caption(
            args,
            stdin,
            stdin_is_tty=stdin_is_tty,
            message_uses_stdin=message_uses_stdin,
        )
        message_text = resolve_message(
            args,
            stdin,
            stdin_is_tty=stdin_is_tty,
            required=not media_source,
            implicit_stdin=message_uses_stdin,
        )
        mode = resolve_mode(args)
        quote_text = None
        if args.quote:
            quote_raw = read_text_file(args.quote, "quote file")
            if quote_raw:
                quote_text = format_quote_block(quote_raw.rstrip("\n"), mode)
        text = build_text_body(args, message_text, quote_text, mode)

        if media_inputs:
            if args.album:
                if len(media_inputs) < 2:
                    raise NotifyError("album mode requires at least two photo items")
                if len(media_inputs) > TELEGRAM_MEDIA_GROUP_LIMIT:
                    raise NotifyError(f"album mode allows up to {TELEGRAM_MEDIA_GROUP_LIMIT} items")
                if any(item["media_kind"] != "photo" for item in media_inputs):
                    raise NotifyError("album mode supports only photo media")
            def send_fallback(opener=None):
                fallback_text = build_fallback_text(text, args.fallback_link, caption_text)
                if args.dry_run:
                    emit_result(
                        stdout,
                        args.json_output,
                        {
                            "ok": True,
                            "method": text_send_method_for_mode(mode),
                            "sent": False,
                            "fallback_sent": False,
                        },
                    )
                    return 0

                token, chat_id, proxy_url = resolve_runtime_settings()
                actual_opener = opener or opener_factory(proxy_url)
                outcome = send_text_body(
                    token,
                    chat_id,
                    args,
                    mode,
                    fallback_text,
                    actual_opener,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                emit_result(
                    stdout,
                    args.json_output,
                    {
                        "ok": True,
                        "method": outcome["method"],
                        "sent": True,
                        "fallback_sent": True,
                        "chunks_sent": outcome["chunks_sent"],
                        "degraded_to_plain": outcome["degraded_to_plain"],
                    },
                )
                return 0

            try:
                for item in media_inputs:
                    source = item["source"]
                    media_kind = item["media_kind"]
                    ensure_local_media_path_exists(source, path_exists)
                    normalized_source = normalize_media_source(source)
                    parsed_source = urlparse(normalized_source)
                    if parsed_source.scheme not in {"http", "https"} and path_exists(normalized_source):
                        ensure_local_media_size(normalized_source, media_kind, stat_fn=stat_fn)
            except NotifyError:
                if not args.fallback_link:
                    raise
                return send_fallback()

            followup_parts: list[str] = []
            if caption_text is not None:
                caption_chunks = chunk_caption_text(caption_text)
                primary_caption = caption_chunks[0] or None
                caption_rest = "".join(caption_chunks[1:])
                if caption_rest:
                    followup_parts.append(caption_rest)
                if text.strip():
                    followup_parts.append(text)
            elif text.strip() and mode != "markdown" and len(text) <= TELEGRAM_CAPTION_LIMIT:
                primary_caption = text
            else:
                primary_caption = None
                if text.strip():
                    followup_parts.append(text)
            followup_text = "\n\n".join(followup_parts)

            if args.album:
                media_methods = ["sendMediaGroup"]
            else:
                media_methods = [
                    "sendPhoto" if item["media_kind"] == "photo" else "sendDocument"
                    for item in media_inputs
                ]
            result_method = (
                media_methods[0] if args.album or len(media_inputs) == 1 else "sendMedia"
            )

            if args.dry_run:
                requests_preview = build_media_requests_preview(
                    args, mode, media_inputs, primary_caption, followup_text
                )
                result = {
                    "ok": True,
                    "method": result_method,
                    "methods": media_methods,
                    "sent": False,
                    "media_sent": False,
                    "followup_sent": False,
                    "fallback_sent": False,
                    "requests": requests_preview,
                }
                if args.json_output:
                    emit_result(stdout, True, result)
                else:
                    stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
                return 0

            token, chat_id, proxy_url = resolve_runtime_settings()
            opener = opener_factory(proxy_url)
            media_sent_count = 0
            try:
                if args.album:
                    group_size = sum(
                        local_media_size(item["source"], path_exists, stat_fn)
                        for item in media_inputs
                    )
                    send_media_group(
                        token,
                        chat_id,
                        args,
                        [item["source"] for item in media_inputs],
                        primary_caption,
                        opener,
                        timeout=compute_upload_timeout(args, group_size),
                        retries=args.retries,
                        path_exists=lambda path: path_exists(str(path)),
                    )
                    media_sent_count = len(media_inputs)
                else:
                    for index, item in enumerate(media_inputs):
                        media_kind = item["media_kind"]
                        item_size = local_media_size(item["source"], path_exists, stat_fn)
                        send_media(
                            token,
                            "sendPhoto" if media_kind == "photo" else "sendDocument",
                            "photo" if media_kind == "photo" else "document",
                            item["source"],
                            build_media_payload(chat_id, args, primary_caption if index == 0 else None, mode),
                            opener,
                            timeout=compute_upload_timeout(args, item_size),
                            retries=args.retries,
                            path_exists=lambda path: path_exists(str(path)),
                        )
                        media_sent_count += 1
            except (NotifyError, urllib.error.HTTPError, urllib.error.URLError):
                if not args.fallback_link or media_sent_count > 0:
                    raise
                return send_fallback(opener=opener)
            degraded_to_plain = False
            followup_chunks_sent = 0
            if followup_text:
                outcome = send_text_body(
                    token,
                    chat_id,
                    args,
                    mode,
                    followup_text,
                    opener,
                    timeout=args.timeout,
                    retries=args.retries,
                )
                degraded_to_plain = outcome["degraded_to_plain"]
                followup_chunks_sent = outcome["chunks_sent"]
            emit_result(
                stdout,
                args.json_output,
                {
                    "ok": True,
                    "method": result_method,
                    "methods": media_methods,
                    "sent": True,
                    "media_sent": True,
                    "followup_sent": bool(followup_text),
                    "followup_chunks_sent": followup_chunks_sent,
                    "degraded_to_plain": degraded_to_plain,
                    "fallback_sent": False,
                },
            )
            return 0

        if args.dry_run:
            requests_preview = [
                {
                    "method": text_send_method_for_mode(mode),
                    "payload": build_payload("<chat_id>", args, chunk, mode),
                }
                for chunk in chunk_text_message(text, max_length=message_limit_for_mode(mode))
            ]
            result = {
                "ok": True,
                "method": text_send_method_for_mode(mode),
                "sent": False,
                "fallback_sent": False,
                "requests": requests_preview,
            }
            if args.json_output:
                emit_result(stdout, True, result)
            else:
                stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            return 0

        token, chat_id, proxy_url = resolve_runtime_settings()
        opener = opener_factory(proxy_url)
        outcome = send_text_body(
            token,
            chat_id,
            args,
            mode,
            text,
            opener,
            timeout=args.timeout,
            retries=args.retries,
        )
        emit_result(
            stdout,
            args.json_output,
            {
                "ok": True,
                "method": outcome["method"],
                "sent": True,
                "chunks_sent": outcome["chunks_sent"],
                "degraded_to_plain": outcome["degraded_to_plain"],
                "fallback_sent": False,
            },
        )
        return 0
    except NotifyError as exc:
        emit_result(stdout, getattr(args, "json_output", False) if "args" in locals() else False, {"ok": False, "error_type": "notify", "message": str(exc)})
        print(f"notify: error: {exc}", file=stderr)
        return 2
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        emit_result(stdout, getattr(args, "json_output", False) if "args" in locals() else False, {"ok": False, "error_type": "http", "status_code": exc.code, "message": detail})
        print(f"notify: HTTP error {exc.code}: {detail}", file=stderr)
        return 1
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        emit_result(stdout, getattr(args, "json_output", False) if "args" in locals() else False, {"ok": False, "error_type": "network", "message": str(reason)})
        print(f"notify: proxy/network error: {reason}", file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
