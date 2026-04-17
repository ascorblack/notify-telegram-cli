#!/usr/bin/env python3
"""Telegram notify CLI."""

from __future__ import annotations

import argparse
import html as html_module
import mimetypes
import json
import os
import sys
from pathlib import Path
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlparse


DEFAULT_PROXY_URL = "http://127.0.0.1:10809"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "notify-telegram-cli" / "config.json"
DEFAULT_TIMEOUT_SECONDS = 20
FILE_ID_PREFIX = "file_id:"
PHOTO_MAX_BYTES = 10 * 1024 * 1024
DOCUMENT_MAX_BYTES = 50 * 1024 * 1024
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024
HTML_QUOTE_OPEN = "<pre><code>"
HTML_QUOTE_CLOSE = "</code></pre>"
PHOTO_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"}
MEDIA_SIZE_LIMITS = {
    "photo": PHOTO_MAX_BYTES,
    "document": DOCUMENT_MAX_BYTES,
}


class NotifyError(Exception):
    """Raised when CLI usage or delivery fails."""


def load_local_config(config_path: Path = DEFAULT_CONFIG_PATH) -> dict[str, object]:
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise NotifyError(f"unable to read local config: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise NotifyError(f"local config is not valid JSON: {exc}") from exc


def resolve_runtime_settings(config_path: Path = DEFAULT_CONFIG_PATH) -> tuple[str, str, str]:
    config = load_local_config(config_path)
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or str(config.get("bot_token") or "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or str(config.get("chat_id") or "")
    proxy_url = os.environ.get("TELEGRAM_PROXY_URL") or str(config.get("proxy_url") or DEFAULT_PROXY_URL)

    if not token:
        raise NotifyError(
            "telegram bot token is not configured; set TELEGRAM_BOT_TOKEN or "
            "~/.config/notify-telegram-cli/config.json"
        )
    if not chat_id:
        raise NotifyError(
            "telegram chat id is not configured; set TELEGRAM_CHAT_ID or "
            "~/.config/notify-telegram-cli/config.json"
        )
    return token, chat_id, proxy_url


def build_parser() -> argparse.ArgumentParser:
    description = (
        "Send a Telegram message through your bot. By default the text is sent as "
        "plain text without parse_mode."
    )
    epilog = """Formatting modes:
  Default:
    Plain text. Telegram will not parse formatting markup.

  --html:
    Use Telegram HTML parse mode. Prefer this when you want readable formatting
    without heavy escaping. Common tags include:
      <b>bold</b>
      <i>italic</i>
      <u>underline</u>
      <s>strikethrough</s>
      <code>inline code</code>
      <pre>code block</pre>
      <a href="https://example.com">link</a>

  --markdownv2:
    Use Telegram MarkdownV2 parse mode. This is stricter and requires escaping
    special characters like: _ * [ ] ( ) ~ ` > # + - = | { } . !

Input modes:
  notify "hello world"
  notify --html "<b>Deploy done</b>"
  printf 'line1\\nline2\\n' | notify -
  notify --markdownv2 -
  notify - <<'EOF'
  first line
  second line
  EOF

Media modes:
  notify --photo screenshot.png --caption "UI after fix"
  notify --file logs.zip --title "Incident logs"
  notify --attach artifact.png --tag nightly --tag success
  notify --file huge.tar --fallback-link https://example.com/huge.tar
  notify --file file_id:ABC123... --caption "reuse Telegram-hosted file"

Limits:
  Upload photo: 10 MB
  Upload document: 50 MB
  URL photo: 5 MB
  URL document: 20 MB

Proxy:
  Requests go through the local Xray HTTP proxy by default:
    http://127.0.0.1:10809
  Override with TELEGRAM_PROXY_URL if needed.

Environment overrides:
  TELEGRAM_BOT_TOKEN   Override bot token
  TELEGRAM_CHAT_ID     Override chat id
  TELEGRAM_PROXY_URL   Override proxy URL

Local config:
  ~/.config/notify-telegram-cli/config.json
"""
    parser = argparse.ArgumentParser(
        prog="notify",
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--html", action="store_true", help="send message with Telegram HTML formatting")
    group.add_argument(
        "--markdownv2",
        action="store_true",
        help="send message with Telegram MarkdownV2 formatting",
    )
    media_group = parser.add_mutually_exclusive_group()
    media_group.add_argument("--photo", metavar="SOURCE", help="send a photo source")
    media_group.add_argument("--file", metavar="SOURCE", help="send a file source")
    media_group.add_argument("--attach", metavar="SOURCE", help="auto-detect photo vs file")
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
    parser.add_argument("--json", action="store_true", help="print JSON output")
    parser.add_argument("--dry-run", action="store_true", help="print the request without sending")
    parser.add_argument("--caption", help="media caption text; pass '-' to read from stdin")
    parser.add_argument(
        "message_parts",
        nargs="*",
        help='message text; pass "-" to read the full message from stdin',
    )
    return parser


def resolve_message(
    args: argparse.Namespace,
    stdin,
    stdin_is_tty: bool,
    required: bool = True,
    implicit_stdin: bool = True,
) -> str:
    if args.message_parts:
        if args.message_parts == ["-"]:
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


def resolve_caption(
    args: argparse.Namespace,
    stdin,
    stdin_is_tty: bool,
    message_uses_stdin: bool = False,
) -> str | None:
    caption = args.caption
    if caption is None:
        return None
    if caption == "-":
        if message_uses_stdin:
            raise NotifyError("caption stdin is ambiguous when message also reads from stdin")
        caption = stdin.read()
    if not caption.strip():
        raise NotifyError("caption text is empty")
    return caption


def build_text_body(args: argparse.Namespace, message_text: str, quote_text: str | None) -> str:
    parts = []
    if args.title:
        parts.append(args.title)
    if args.tag:
        parts.append(f"Tags: {', '.join(args.tag)}")
    if args.link:
        parts.append(f"Links: {' '.join(args.link)}")
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


def chunk_text(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    return chunk_text_message(text, max_length=limit)


def chunk_caption_text(text: str, max_length: int = TELEGRAM_CAPTION_LIMIT) -> list[str]:
    if max_length <= 0:
        raise ValueError("limit must be positive")
    if not text:
        return [""]
    return [text[index : index + max_length] for index in range(0, len(text), max_length)] or [""]


def format_quote_block(text: str, parse_mode=None) -> str:
    if parse_mode in {"HTML", "html"} or parse_mode is True:
        return f"{HTML_QUOTE_OPEN}{html_module.escape(text)}{HTML_QUOTE_CLOSE}"
    if parse_mode in {"MarkdownV2", "markdownv2"}:
        replacements = {
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

        def escape_markdown_v2(line: str) -> str:
            return "".join(replacements.get(char, char) for char in line)

        return "\n".join(f"> {escape_markdown_v2(line)}" if line else ">" for line in text.splitlines())
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


def build_payload(chat_id: str, args: argparse.Namespace, text: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "chat_id": chat_id,
        "text": text,
    }
    if args.html:
        payload["parse_mode"] = "HTML"
    elif args.markdownv2:
        payload["parse_mode"] = "MarkdownV2"
    if args.disable_web_preview:
        payload["disable_web_page_preview"] = True
    if args.silent:
        payload["disable_notification"] = True
    return payload


def build_http_opener(proxy_url: str):
    proxy_handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    return urllib.request.build_opener(proxy_handler)


def build_json_request(token: str, method: str, payload: dict[str, object]) -> urllib.request.Request:
    return urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


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


def send_message(token: str, payload: dict[str, object], opener, timeout: int = DEFAULT_TIMEOUT_SECONDS):
    request = build_json_request(token, "sendMessage", payload)
    with opener.open(request, timeout=timeout) as response:
        raw_body = response.read()

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NotifyError(f"Telegram API returned invalid JSON: {raw_body!r}") from exc

    if not body.get("ok"):
        description = body.get("description", "unknown Telegram API error")
        raise NotifyError(f"Telegram API error: {description}")
    return body


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


def build_media_payload(chat_id: str, args: argparse.Namespace, caption: str | None) -> dict[str, object]:
    payload: dict[str, object] = {"chat_id": chat_id}
    if caption:
        payload["caption"] = caption
    if args.html:
        payload["parse_mode"] = "HTML"
    elif args.markdownv2:
        payload["parse_mode"] = "MarkdownV2"
    if args.disable_web_preview:
        payload["disable_web_page_preview"] = True
    if args.silent:
        payload["disable_notification"] = True
    return payload


def send_media(
    token: str,
    method: str,
    source_field: str,
    source: str,
    payload: dict[str, object],
    opener,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
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

    with opener.open(request, timeout=timeout) as response:
        raw_body = response.read()

    try:
        body = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise NotifyError(f"Telegram API returned invalid JSON: {raw_body!r}") from exc

    if not body.get("ok"):
        description = body.get("description", "unknown Telegram API error")
        raise NotifyError(f"Telegram API error: {description}")
    return body


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
        media_source = args.photo or args.file or args.attach
        message_uses_stdin = args.message_parts == ["-"] or (
            not args.message_parts
            and not stdin_is_tty
            and not (media_source and args.caption == "-")
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
        parse_mode = "HTML" if args.html else "MarkdownV2" if args.markdownv2 else None
        quote_text = None
        if args.quote:
            try:
                quote_source = Path(args.quote)
                quote_raw = quote_source.read_text(encoding="utf-8")
            except OSError as exc:
                raise NotifyError(f"unable to read quote file: {exc}") from exc
            if quote_raw:
                quote_text = format_quote_block(quote_raw.rstrip("\n"), parse_mode)
        text = build_text_body(args, message_text, quote_text)

        if media_source:
            media_kind = "photo" if args.photo else "document"
            if args.attach:
                media_kind = classify_media_source(media_source)
            method = "sendPhoto" if media_kind == "photo" else "sendDocument"
            ensure_local_media_path_exists(media_source, path_exists)

            try:
                parsed_source = urlparse(media_source)
                if parsed_source.scheme not in {"http", "https"} and path_exists(media_source):
                    ensure_local_media_size(media_source, media_kind, stat_fn=stat_fn)
            except NotifyError:
                if not args.fallback_link:
                    raise
                fallback_text = build_fallback_text(text, args.fallback_link, caption_text)
                if args.dry_run:
                    emit_result(
                        stdout,
                        args.json,
                        {
                            "ok": True,
                            "method": "sendMessage",
                            "sent": False,
                            "fallback_sent": False,
                        },
                    )
                    return 0

                token, chat_id, proxy_url = resolve_runtime_settings()
                opener = opener_factory(proxy_url)
                fallback_chunks_sent = 0
                for chunk in chunk_text_message(fallback_text):
                    send_message(token, build_payload(chat_id, args, chunk), opener)
                    fallback_chunks_sent += 1
                emit_result(
                    stdout,
                    args.json,
                    {
                        "ok": True,
                        "method": "sendMessage",
                        "sent": True,
                        "fallback_sent": True,
                        "chunks_sent": fallback_chunks_sent,
                    },
                )
                return 0

            caption_chunks = chunk_caption_text(caption_text or text)
            media_caption = caption_chunks[0] if caption_chunks and caption_chunks[0] else None
            followup_chunks = caption_chunks[1:]
            if caption_text is not None and text.strip():
                followup_chunks.extend(chunk_text_message(text))

            if args.dry_run:
                emit_result(
                    stdout,
                    args.json,
                    {
                        "ok": True,
                        "method": method,
                        "sent": False,
                        "media_sent": False,
                        "followup_sent": False,
                        "fallback_sent": False,
                    },
                )
                return 0

            token, chat_id, proxy_url = resolve_runtime_settings()
            opener = opener_factory(proxy_url)
            try:
                send_media(
                    token,
                    method,
                    "photo" if media_kind == "photo" else "document",
                    media_source,
                    build_media_payload(chat_id, args, media_caption),
                    opener,
                    path_exists=lambda path: path_exists(str(path)),
                )
            except (NotifyError, urllib.error.HTTPError, urllib.error.URLError):
                if not args.fallback_link:
                    raise
                fallback_text = build_fallback_text(text, args.fallback_link, caption_text)
                fallback_chunks_sent = 0
                for chunk in chunk_text_message(fallback_text):
                    send_message(token, build_payload(chat_id, args, chunk), opener)
                    fallback_chunks_sent += 1
                emit_result(
                    stdout,
                    args.json,
                    {
                        "ok": True,
                        "method": "sendMessage",
                        "sent": True,
                        "fallback_sent": True,
                        "chunks_sent": fallback_chunks_sent,
                    },
                )
                return 0
            for chunk in followup_chunks:
                send_message(token, build_payload(chat_id, args, chunk), opener)
            emit_result(
                stdout,
                args.json,
                {
                    "ok": True,
                    "method": method,
                    "sent": True,
                    "media_sent": True,
                    "followup_sent": bool(followup_chunks),
                    "fallback_sent": False,
                },
            )
            return 0

        token, chat_id, proxy_url = resolve_runtime_settings()
        opener = opener_factory(proxy_url)
        chunks_sent = 0
        for chunk in chunk_text_message(text):
            send_message(token, build_payload(chat_id, args, chunk), opener)
            chunks_sent += 1
        emit_result(
            stdout,
            args.json,
            {
                "ok": True,
                "method": "sendMessage",
                "sent": True,
                "chunks_sent": chunks_sent,
                "fallback_sent": False,
            },
        )
        return 0
    except NotifyError as exc:
        print(f"notify: error: {exc}", file=stderr)
        return 2
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        print(f"notify: HTTP error {exc.code}: {detail}", file=stderr)
        return 1
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        print(f"notify: proxy/network error: {reason}", file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
