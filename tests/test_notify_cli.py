import json
import io
import os
import subprocess
import sys
import unittest
import tempfile
import urllib.error
from pathlib import Path


MODULE_DIR = Path(__file__).resolve().parent.parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import notify_cli  # noqa: E402


class NotifyCliTests(unittest.TestCase):
    def setUp(self):
        self.module = notify_cli
        self.parser = self.module.build_parser()

    def parse(self, argv):
        return self.parser.parse_args(argv)

    def test_build_message_from_args(self):
        args = self.parse(["hello", "world"])
        self.assertEqual(
            self.module.resolve_message(args, io.StringIO(""), stdin_is_tty=True),
            "hello world",
        )

    def test_reads_message_from_stdin_with_dash(self):
        args = self.parse(["-"])
        self.assertEqual(
            self.module.resolve_message(args, io.StringIO("line1\nline2\n"), stdin_is_tty=False),
            "line1\nline2\n",
        )

    def test_html_and_markdown_flags_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self.parse(["--html", "--markdownv2", "hello"])

    def test_parser_preserves_ordered_media_items(self):
        args = self.parse(
            [
                "--photo",
                "a.png",
                "--file",
                "b.zip",
                "--photo-id",
                "AgACAgIA...",
            ]
        )
        self.assertEqual(
            args.media_items,
            [("photo", "a.png"), ("file", "b.zip"), ("photo_id", "AgACAgIA...")],
        )

    def test_parser_accepts_agent_facing_flags(self):
        args = self.parse(
            [
                "--attach",
                "artifact.png",
                "--title",
                "Deploy finished",
                "--tag",
                "deploy",
                "--tag",
                "success",
                "--link",
                "https://example.com/run/123",
                "--json-output",
                "--dry-run",
            ]
        )
        self.assertEqual(args.attach, "artifact.png")
        self.assertEqual(args.title, "Deploy finished")
        self.assertEqual(args.tag, ["deploy", "success"])
        self.assertEqual(args.link, ["https://example.com/run/123"])
        self.assertTrue(args.json_output)
        self.assertTrue(args.dry_run)

    def test_parser_accepts_explicit_agent_input_flags(self):
        args = self.parse(
            [
                "--photo-id",
                "AgACAgIA...",
                "--message-file",
                "body.txt",
                "--caption-file",
                "caption.txt",
                "--retries",
                "3",
                "--timeout",
                "12",
            ]
        )
        self.assertEqual(args.photo_id, "AgACAgIA...")
        self.assertEqual(args.message_file, "body.txt")
        self.assertEqual(args.caption_file, "caption.txt")
        self.assertEqual(args.retries, 3)
        self.assertEqual(args.timeout, 12)

    def test_parser_accepts_json_input_flag(self):
        args = self.parse(["--json", '{"message":"hello"}'])
        self.assertEqual(args.json, '{"message":"hello"}')

    def test_parser_accepts_doctor_flag(self):
        args = self.parse(["--doctor", "--json-output"])
        self.assertTrue(args.doctor)
        self.assertTrue(args.json_output)

    def test_apply_json_input_parses_string_bools_safely(self):
        args = self.parse([])
        args = self.module.apply_json_input(
            args,
            {
                "silent": "false",
                "disable_web_preview": "0",
                "album": "no",
            },
        )

        self.assertFalse(args.silent)
        self.assertFalse(args.disable_web_preview)
        self.assertFalse(args.album)

    def test_apply_json_input_rejects_invalid_parse_mode(self):
        args = self.parse(["--html"])

        with self.assertRaisesRegex(self.module.NotifyError, "parse_mode"):
            self.module.apply_json_input(args, {"parse_mode": "bogus"})

    def test_caption_flags_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self.parse(["--caption", "hello", "--caption-file", "caption.txt"])

    def test_caption_dash_marks_stdin_caption(self):
        args = self.parse(["--photo", "a.png", "--caption", "-"])
        self.assertEqual(args.caption, "-")

    def test_caption_can_be_read_from_stdin(self):
        args = self.parse(["--photo", "a.png", "--caption", "-"])
        self.assertEqual(
            self.module.resolve_caption(
                args,
                io.StringIO("media caption\n"),
                stdin_is_tty=False,
                message_uses_stdin=False,
            ),
            "media caption\n",
        )

    def test_resolve_message_reads_message_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as message_file:
            message_file.write("message from file\n")
            message_path = message_file.name

        try:
            args = self.parse(["--message-file", message_path])
            self.assertEqual(
                self.module.resolve_message(args, io.StringIO(""), stdin_is_tty=True),
                "message from file\n",
            )
        finally:
            os.unlink(message_path)

    def test_message_file_is_mutually_exclusive_with_inline_message(self):
        with self.assertRaises(SystemExit):
            self.parse(["--message-file", "body.txt", "hello"])

    def test_resolve_caption_reads_caption_file(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as caption_file:
            caption_file.write("caption from file\n")
            caption_path = caption_file.name

        try:
            args = self.parse(["--photo", "a.png", "--caption-file", caption_path])
            self.assertEqual(
                self.module.resolve_caption(
                    args,
                    io.StringIO(""),
                    stdin_is_tty=True,
                    message_uses_stdin=False,
                ),
                "caption from file\n",
            )
        finally:
            os.unlink(caption_path)

    def test_caption_from_stdin_rejects_whitespace_only_input(self):
        args = self.parse(["--photo", "a.png", "--caption", "-", "hello"])
        with self.assertRaisesRegex(self.module.NotifyError, "caption text is empty"):
            self.module.resolve_caption(
                args,
                io.StringIO("   \n\t"),
                stdin_is_tty=True,
                message_uses_stdin=False,
            )

    def test_caption_from_stdin_rejects_ambiguous_shared_stdin(self):
        args = self.parse(["--caption", "-", "-"])
        with self.assertRaisesRegex(self.module.NotifyError, "ambiguous"):
            self.module.resolve_caption(
                args,
                io.StringIO("shared stdin"),
                stdin_is_tty=False,
                message_uses_stdin=True,
            )

    def test_caption_overflow_moves_extra_text_to_follow_up(self):
        chunks = self.module.chunk_caption_text("x" * 1025, max_length=1024)

        self.assertEqual(chunks, ["x" * 1024, "x"])
        self.assertEqual("".join(chunks), "x" * 1025)

    def test_caption_chunking_preserves_raw_html_sensitive_characters(self):
        caption = "<tag>&value"
        chunks = self.module.chunk_caption_text(caption, max_length=5)

        self.assertEqual(chunks, ["<tag>", "&valu", "e"])
        self.assertEqual("".join(chunks), caption)

    def test_classifies_local_png_as_photo(self):
        self.assertEqual(self.module.classify_media_source("image.png"), "photo")

    def test_classifies_unknown_url_as_document(self):
        self.assertEqual(self.module.classify_media_source("https://example.com/download"), "document")

    def test_rejects_oversized_local_photo_upload(self):
        class DummyStat:
            st_size = 10 * 1024 * 1024 + 1

        with self.assertRaisesRegex(
            self.module.NotifyError, "photo.*10 MB"
        ):
            self.module.ensure_local_media_size(
                "image.png",
                "photo",
                stat_fn=lambda path: DummyStat(),
            )

    def test_allows_50mb_local_document_upload(self):
        class DummyStat:
            st_size = 50 * 1024 * 1024

        self.module.ensure_local_media_size(
            "archive.zip",
            "document",
            stat_fn=lambda path: DummyStat(),
        )

    def test_rejects_unknown_media_kind_for_local_size_check(self):
        with self.assertRaisesRegex(self.module.NotifyError, "unsupported media kind"):
            self.module.ensure_local_media_size("mystery.bin", "audio")

    def test_remote_sources_bypass_local_stat_checks(self):
        def fail_stat(path):
            raise AssertionError("stat should not be called for remote sources")

        self.module.ensure_local_media_size(
            "https://example.com/image.png",
            "photo",
            stat_fn=fail_stat,
        )
        self.module.ensure_local_media_size(
            "http://example.com/archive.zip",
            "document",
            stat_fn=fail_stat,
        )

    def test_build_payload_for_html(self):
        args = self.parse(["--html", "hello"])
        payload = self.module.build_payload("123", args, "hello")
        self.assertEqual(payload["chat_id"], "123")
        self.assertEqual(payload["text"], "hello")
        self.assertEqual(payload["parse_mode"], "HTML")

    def test_build_text_body_uses_title_tags_links_and_message(self):
        args = self.parse(
            [
                "--title",
                "Deploy finished",
                "--tag",
                "deploy",
                "--tag",
                "success",
                "--link",
                "https://example.com/run/123",
                "Build passed",
            ]
        )
        body = self.module.build_text_body(args, "Build passed", None)

        self.assertEqual(
            body,
            "Deploy finished\n\nTags: deploy, success\n\nLinks: https://example.com/run/123\n\nBuild passed",
        )

    def test_build_text_body_includes_event_and_meta_blocks(self):
        args = self.parse(["Build passed"])
        args.event = {
            "type": "deploy",
            "name": "nightly",
            "status": "success",
            "phase": "rollout",
            "id": "run-123",
            "summary": "All checks passed",
        }
        args.meta = {
            "branch": "main",
            "commit": "abc123",
            "services": ["api", "worker"],
        }

        body = self.module.build_text_body(args, "Build passed", None)

        self.assertIn("Event: deploy / nightly", body)
        self.assertIn("Status: success", body)
        self.assertIn("Phase: rollout", body)
        self.assertIn("ID: run-123", body)
        self.assertIn("Summary: All checks passed", body)
        self.assertIn("Meta:", body)
        self.assertIn("branch: main", body)
        self.assertIn("services: api, worker", body)

    def test_chunk_text_message_preserves_lines(self):
        text = "alpha\nbeta\ngamma"
        chunks = self.module.chunk_text_message(text, max_length=8)

        self.assertEqual(chunks, ["alpha\n", "beta\n", "gamma"])
        self.assertTrue(all(len(chunk) <= 8 for chunk in chunks))
        self.assertEqual("".join(chunks), text)

    def test_format_quote_block_uses_html_code_block_for_html_parse_mode(self):
        formatted = self.module.format_quote_block(
            "line 1\nline 2",
            "HTML",
        )

        self.assertEqual(formatted, "<pre><code>line 1\nline 2</code></pre>")

    def test_format_quote_block_escapes_markdownv2_backticks(self):
        formatted = self.module.format_quote_block(
            "deploy log:\n```bash\necho hi\n```",
            "MarkdownV2",
        )

        self.assertIn("> deploy log:", formatted)
        self.assertIn("> \\`\\`\\`bash", formatted)
        self.assertNotIn("```", formatted)

    def test_main_includes_quote_file_text_in_plain_body(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 1}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout=None):
                self.request = request
                return DummyResponse()

        dummy_opener = DummyOpener()
        with tempfile.NamedTemporaryFile("w", delete=False) as quote_file:
            quote_file.write("quoted line\nsecond line\n")
            quote_path = quote_file.name

        try:
            stderr = io.StringIO()
            exit_code = self.module.main(
                ["--plain", "--quote", quote_path, "hello"],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=stderr,
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: dummy_opener,
            )
        finally:
            os.unlink(quote_path)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("> quoted line", dummy_opener.request.data.decode("utf-8"))
        self.assertIn("hello", dummy_opener.request.data.decode("utf-8"))

    def test_main_keeps_html_quote_block_whole_while_chunking(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 1}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return DummyResponse()

        dummy_opener = DummyOpener()
        with tempfile.NamedTemporaryFile("w", delete=False) as quote_file:
            quote_file.write("x" * 5000)
            quote_path = quote_file.name

        try:
            stderr = io.StringIO()
            exit_code = self.module.main(
                ["--html", "--quote", quote_path, "hello"],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=stderr,
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: dummy_opener,
            )
        finally:
            os.unlink(quote_path)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertGreater(len(dummy_opener.requests), 1)
        payloads = [json.loads(request.data.decode("utf-8")) for request in dummy_opener.requests]
        self.assertTrue(all(payload["parse_mode"] == "HTML" for payload in payloads))
        self.assertTrue(all(len(payload["text"]) <= 4096 for payload in payloads))
        self.assertTrue(all(text.startswith("<pre><code>") and text.endswith("</code></pre>") for text in [payload["text"] for payload in payloads[:-1]]))
        combined = "".join(
            payload["text"].replace("<pre><code>", "").replace("</code></pre>", "")
            for payload in payloads
        )
        self.assertEqual(combined, ("x" * 5000) + "\n\nhello")

    def test_build_http_opener_uses_proxy_for_http_and_https(self):
        opener = self.module.build_http_opener("http://127.0.0.1:10809")
        proxy_handler = next(
            handler for handler in opener.handlers if handler.__class__.__name__ == "ProxyHandler"
        )
        self.assertEqual(proxy_handler.proxies["http"], "http://127.0.0.1:10809")
        self.assertEqual(proxy_handler.proxies["https"], "http://127.0.0.1:10809")

    def test_compute_retry_delay_uses_retry_after_header(self):
        error = urllib.error.HTTPError(
            "https://example.com",
            429,
            "Too Many Requests",
            {"Retry-After": "3"},
            io.BytesIO(b""),
        )

        delay = self.module.compute_retry_delay(error, 0)

        self.assertEqual(delay, 3.0)

    def test_compute_retry_delay_uses_exponential_backoff_for_network_errors(self):
        delay = self.module.compute_retry_delay(urllib.error.URLError("boom"), 2)
        self.assertEqual(delay, 1.0)

    def test_send_message_posts_json_payload(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout=None):
                self.request = request
                return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

        opener = DummyOpener()
        result = self.module.send_message("token", {"chat_id": "123", "text": "hello"}, opener)
        self.assertTrue(result["ok"])
        self.assertIn("/bottoken/sendMessage", opener.request.full_url)
        self.assertEqual(opener.request.get_header("Content-type"), "application/json")
        self.assertEqual(opener.request.data, b'{"chat_id":"123","text":"hello"}')

    def test_send_message_retries_on_urlerror_and_succeeds(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.calls = 0

            def open(self, request, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise self_module.urllib.error.URLError("temporary failure")
                return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

        self_module = self.module
        opener = DummyOpener()
        result = self.module.send_message(
            "token",
            {"chat_id": "123", "text": "hello"},
            opener,
            retries=1,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(opener.calls, 2)

    def test_send_message_retries_on_http_429_and_succeeds(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.calls = 0

            def open(self, request, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    fp = io.BytesIO(b'{"ok": false, "description": "Too Many Requests"}')
                    raise self_module.urllib.error.HTTPError(
                        request.full_url,
                        429,
                        "Too Many Requests",
                        hdrs=None,
                        fp=fp,
                    )
                return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

        self_module = self.module
        opener = DummyOpener()
        result = self.module.send_message(
            "token",
            {"chat_id": "123", "text": "hello"},
            opener,
            retries=1,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(opener.calls, 2)

    def test_build_json_request_for_send_message(self):
        request = self.module.build_json_request(
            "token",
            "sendMessage",
            {"chat_id": "123", "text": "hello"},
        )

        self.assertEqual(request.full_url, "https://api.telegram.org/bottoken/sendMessage")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.data, b'{"chat_id":"123","text":"hello"}')

    def test_build_multipart_request_for_photo_upload(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name

        try:
            request = self.module.build_multipart_request(
                "token",
                "sendPhoto",
                {"chat_id": "123", "caption": "hello"},
                {"photo": photo_path},
            )
        finally:
            os.unlink(photo_path)

        boundary = request.get_header("Content-type").split("boundary=", 1)[1]
        expected_body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="chat_id"\r\n'
            "\r\n"
            "123\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="caption"\r\n'
            "\r\n"
            "hello\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="photo"; filename="{Path(photo_path).name}"\r\n'
            "Content-Type: image/png\r\n"
            "\r\n"
            "PNGDATA\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")

        self.assertEqual(request.full_url, "https://api.telegram.org/bottoken/sendPhoto")
        self.assertEqual(request.get_header("Content-type"), f"multipart/form-data; boundary={boundary}")
        self.assertEqual(request.data, expected_body)

    def test_build_multipart_request_normalizes_boolean_fields(self):
        request = self.module.build_multipart_request(
            "token",
            "sendMessage",
            {"chat_id": "123", "disable_web_page_preview": False, "disable_notification": True},
            {},
        )

        body = request.data
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="disable_web_page_preview"\r\n\r\nfalse\r\n', body)
        self.assertIn(b'name="disable_notification"\r\n\r\ntrue\r\n', body)
        self.assertNotIn(b"False", body)
        self.assertNotIn(b"True", body)

    def test_help_mentions_html_markdown_proxy_and_stdin(self):
        help_text = self.parser.format_help()
        self.assertIn("--html", help_text)
        self.assertIn("--markdownv2", help_text)
        self.assertIn("stdin", help_text.lower())
        self.assertIn("proxy", help_text.lower())

    def test_help_mentions_photo_file_attach_and_limits(self):
        help_text = self.module.build_parser().format_help()
        self.assertIn("--photo", help_text)
        self.assertIn("--file", help_text)
        self.assertIn("--attach", help_text)
        self.assertIn("--album", help_text)
        self.assertIn("--photo-id", help_text)
        self.assertIn("--file-id", help_text)
        self.assertIn("--message-file", help_text)
        self.assertIn("--caption-file", help_text)
        self.assertIn("10 MB", help_text)
        self.assertIn("50 MB", help_text)
        self.assertIn("10809", help_text)
        self.assertIn("--fallback-link", help_text)

    def test_wrapper_contract_matches_installed_launcher_template(self):
        script = (MODULE_DIR / "scripts" / "lib" / "install-common.sh").read_text(encoding="utf-8")
        self.assertIn('exec env NOTIFY_LAUNCHER_PATH="\\$0" python3 "$repo_root/notify_cli.py" "\\$@"', script)

    def test_main_errors_on_empty_message(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            [],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
        )
        self.assertEqual(exit_code, 2)
        self.assertIn("message", stderr.getvalue().lower())

    def test_main_prints_json_error_result(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = self.module.main(
            ["--json-output"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=stderr,
            stdin_is_tty=True,
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "notify")
        self.assertIn("message", result["message"].lower())

    def test_main_reads_message_from_json_input(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 14}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout=None):
                self.request = request
                return DummyResponse()

        dummy_opener = DummyOpener()
        exit_code = self.module.main(
            ['--json', '{"message":"hello from json","title":"Deploy"}'],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            stdin_is_tty=True,
            opener_factory=lambda proxy_url: dummy_opener,
        )

        self.assertEqual(exit_code, 0)
        self.assertIn("/sendRichMessage", dummy_opener.request.full_url)
        payload = json.loads(dummy_opener.request.data.decode("utf-8"))
        self.assertEqual(payload["rich_message"]["markdown"], "**Deploy**\n\nhello from json")

    def test_main_reads_json_aliases_event_and_meta(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 18}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout=None):
                self.request = request
                return DummyResponse()

        dummy_opener = DummyOpener()
        exit_code = self.module.main(
            [
                "--json",
                '{"message":"done","tags":["nightly","success"],"links":["https://example.com/run/123"],'
                '"event":{"type":"deploy","name":"nightly","status":"success","id":"run-123"},'
                '"meta":{"branch":"main","services":["api","worker"]}}',
            ],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            stdin_is_tty=True,
            opener_factory=lambda proxy_url: dummy_opener,
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(dummy_opener.request.data.decode("utf-8"))
        body = payload["rich_message"]["markdown"]
        self.assertIn("Tags: nightly, success", body)
        self.assertIn("Links: https://example.com/run/123", body)
        self.assertIn("Event: deploy / nightly", body)
        self.assertIn("ID: run-123", body)
        self.assertIn("branch: main", body)

    def test_main_reads_media_from_json_input(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            ['--json', '{"message":"body","caption":"cap","media":[{"type":"photo","source":"/tmp/example.png"}]}', "--dry-run", "--json-output"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=True,
            path_exists=lambda path: True,
            stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["method"], "sendPhoto")
        self.assertFalse(result["sent"])

    def test_main_doctor_reports_ok_json_result(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                if request.full_url.endswith("/getMe"):
                    return DummyResponse(
                        b'{"ok": true, "result": {"id": 1, "is_bot": true, "username": "notify_bot"}}'
                    )
                if request.full_url.endswith("/getChat"):
                    return DummyResponse(
                        b'{"ok": true, "result": {"id": 999, "type": "private"}}'
                    )
                raise AssertionError(f"unexpected request url: {request.full_url}")

        stdout = io.StringIO()
        stderr = io.StringIO()
        old_env = os.environ.copy()
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                ["--doctor", "--json-output"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: DummyOpener(),
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "doctor")
        self.assertIn("checks", result)
        self.assertEqual(stderr.getvalue(), "")

    def test_main_doctor_warns_when_token_missing(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        old_env = os.environ.copy()
        temp_home = tempfile.mkdtemp(prefix="notify-doctor-home-")
        try:
            os.environ["HOME"] = temp_home
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            os.environ.pop("TELEGRAM_CHAT_ID", None)
            os.environ.pop("TELEGRAM_PROXY_URL", None)
            exit_code = self.module.main(
                ["--doctor", "--json-output"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: self.fail("network should not be used"),
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertEqual(result["command"], "doctor")
        self.assertFalse(result["ready_to_send"])
        token_check = next(check for check in result["checks"] if check["name"] == "token")
        self.assertEqual(token_check["status"], "warn")
        self.assertEqual(stderr.getvalue(), "")

    def test_main_doctor_respects_custom_install_env_paths(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                if request.full_url.endswith("/getMe"):
                    return DummyResponse(
                        b'{"ok": true, "result": {"id": 1, "is_bot": true, "username": "notify_bot"}}'
                    )
                if request.full_url.endswith("/getChat"):
                    return DummyResponse(
                        b'{"ok": true, "result": {"id": 999, "type": "private"}}'
                    )
                raise AssertionError(f"unexpected request url: {request.full_url}")

        temp_home = tempfile.mkdtemp(prefix="notify-doctor-paths-")
        custom_codex = Path(temp_home) / "codex-home"
        custom_agents = Path(temp_home) / "agents-home" / "skills"
        custom_claude = Path(temp_home) / "claude-home"
        custom_bin = Path(temp_home) / "bin"
        for path in (
            custom_codex / "skills" / "notify-telegram",
            custom_agents / "notify-telegram",
            custom_claude / "skills" / "notify-telegram",
            custom_bin,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for skill_file in (
            custom_codex / "skills" / "notify-telegram" / "SKILL.md",
            custom_agents / "notify-telegram" / "SKILL.md",
            custom_claude / "skills" / "notify-telegram" / "SKILL.md",
        ):
            skill_file.write_text("# skill\n", encoding="utf-8")
        launcher = custom_bin / "notify"
        launcher.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        launcher.chmod(0o755)

        stdout = io.StringIO()
        stderr = io.StringIO()
        old_env = os.environ.copy()
        old_path = os.environ.get("PATH", "")
        try:
            os.environ["HOME"] = temp_home
            os.environ["CODEX_HOME"] = str(custom_codex)
            os.environ["LEGACY_AGENTS_SKILL_DIR"] = str(custom_agents)
            os.environ["CLAUDE_HOME"] = str(custom_claude)
            os.environ["NOTIFY_INSTALL_BIN_DIR"] = str(custom_bin)
            os.environ["PATH"] = f"{custom_bin}:{old_path}"
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                ["--doctor", "--json-output"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: DummyOpener(),
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ready_to_send"])
        checks = {check["name"]: check for check in result["checks"]}
        self.assertEqual(checks["codex_skill"]["status"], "ok")
        self.assertEqual(checks["agents_skill"]["status"], "ok")
        self.assertEqual(checks["claude_skill"]["status"], "ok")
        self.assertEqual(checks["launcher"]["status"], "ok")
        self.assertEqual(stderr.getvalue(), "")

    def test_main_rejects_json_input_with_inline_message(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            ['--json', '{"message":"hello"}', "extra"],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("--json", stderr.getvalue())

    def test_main_rejects_json_input_without_message_even_with_stdin(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            ['--json', '{"title":"Deploy"}'],
            stdin=io.StringIO("unexpected stdin body"),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=False,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("message", stderr.getvalue().lower())

    def test_main_treats_dash_message_in_json_as_literal_text(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 15}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout=None):
                self.request = request
                return DummyResponse()

        dummy_opener = DummyOpener()
        exit_code = self.module.main(
            ['--json', '{"message":"-"}'],
            stdin=io.StringIO("unexpected stdin body"),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
            stdin_is_tty=False,
            opener_factory=lambda proxy_url: dummy_opener,
        )

        self.assertEqual(exit_code, 0)
        payload = json.loads(dummy_opener.request.data.decode("utf-8"))
        self.assertEqual(payload["rich_message"]["markdown"], "-")

    def test_main_treats_dash_caption_in_json_as_literal_text(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            ['--json', '{"caption":"-","media":[{"type":"photo","source":"/tmp/example.png"}]}', "--dry-run", "--json-output"],
            stdin=io.StringIO("unexpected caption body"),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=False,
            path_exists=lambda path: True,
            stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["method"], "sendPhoto")

    def test_main_dry_run_reports_send_photo_without_network(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            ["--photo", "/tmp/example.png", "--dry-run", "--json-output", "hello"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=True,
            path_exists=lambda path: True,
            stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["method"], "sendPhoto")
        self.assertFalse(result["sent"])

    def test_main_dry_run_reports_send_document_for_file_id_flag(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            ["--file-id", "AgACAgIA...", "--dry-run", "--json-output"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=True,
            path_exists=lambda path: False,
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["method"], "sendDocument")
        self.assertFalse(result["sent"])

    def test_main_dry_run_reports_media_group_for_album(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            [
                "--album",
                "--photo",
                "/tmp/one.png",
                "--photo-id",
                "AgACAgIAAlbum",
                "--dry-run",
                "--json-output",
                "album body",
            ],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=True,
            path_exists=lambda path: path == "/tmp/one.png",
            stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["method"], "sendMediaGroup")
        self.assertFalse(result["sent"])

    def test_main_rejects_album_with_document_media(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            ["--album", "--photo", "one.png", "--file", "two.zip", "album body"],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("album", stderr.getvalue().lower())

    def test_main_sends_multiple_media_sequentially_in_order(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return DummyResponse(b'{"ok": true, "result": {"message_id": 21}}')

        opener = DummyOpener()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as doc_file:
            doc_file.write(b"DOCDATA")
            doc_path = doc_file.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                [
                    "--photo",
                    photo_path,
                    "--file",
                    doc_path,
                    "--caption",
                    "batch caption",
                    "batch body",
                ],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.unlink(doc_path)
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(opener.requests), 3)
        self.assertIn("/botenv-token/sendPhoto", opener.requests[0].full_url)
        self.assertIn("/botenv-token/sendDocument", opener.requests[1].full_url)
        self.assertIn("/botenv-token/sendRichMessage", opener.requests[2].full_url)

    def test_main_does_not_send_fallback_after_partial_multi_send_failure(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []
                self.responses = [
                    DummyResponse(b'{"ok": true, "result": {"message_id": 30}}'),
                    DummyResponse(b'{"ok": false, "description": "Bad Request: failed to send"}'),
                ]

            def open(self, request, timeout=None):
                self.requests.append(request)
                return self.responses.pop(0)

        opener = DummyOpener()
        stderr = io.StringIO()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as doc_file:
            doc_file.write(b"DOCDATA")
            doc_path = doc_file.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                [
                    "--photo",
                    photo_path,
                    "--file",
                    doc_path,
                    "--fallback-link",
                    "https://example.com/fallback",
                    "--caption",
                    "batch caption",
                    "batch body",
                ],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=stderr,
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.unlink(doc_path)
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 2)
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("/botenv-token/sendPhoto", opener.requests[0].full_url)
        self.assertIn("/botenv-token/sendDocument", opener.requests[1].full_url)
        self.assertNotIn("fallback", stderr.getvalue().lower())

    def test_main_sends_fallback_when_first_multi_send_item_fails(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []
                self.responses = [
                    DummyResponse(b'{"ok": false, "description": "Bad Request: failed to send"}'),
                    DummyResponse(b'{"ok": true, "result": {"message_id": 31}}'),
                ]

            def open(self, request, timeout=None):
                self.requests.append(request)
                return self.responses.pop(0)

        opener = DummyOpener()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as doc_file:
            doc_file.write(b"DOCDATA")
            doc_path = doc_file.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                [
                    "--photo",
                    photo_path,
                    "--file",
                    doc_path,
                    "--fallback-link",
                    "https://example.com/fallback",
                    "--caption",
                    "batch caption",
                    "batch body",
                ],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.unlink(doc_path)
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("/botenv-token/sendPhoto", opener.requests[0].full_url)
        self.assertIn("/botenv-token/sendRichMessage", opener.requests[1].full_url)
        self.assertIn("https://example.com/fallback", opener.requests[1].data.decode("utf-8"))

    def test_main_rejects_album_over_ten_items(self):
        stderr = io.StringIO()
        argv = ["--album"]
        for index in range(11):
            argv.extend(["--photo", f"/tmp/photo-{index}.png"])
        argv.append("album body")

        exit_code = self.module.main(
            argv,
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
            path_exists=lambda path: True,
            stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("10", stderr.getvalue())

    def test_main_allows_media_with_caption_without_message(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            ["--photo", "/tmp/example.png", "--caption", "inline image smoke check", "--dry-run", "--json-output"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=True,
            path_exists=lambda path: True,
            stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["method"], "sendPhoto")
        self.assertFalse(result["sent"])

    def test_main_uses_message_file_for_text_delivery(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 12}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout=None):
                self.request = request
                return DummyResponse()

        dummy_opener = DummyOpener()
        with tempfile.NamedTemporaryFile("w", delete=False) as message_file:
            message_file.write("message from file\n")
            message_path = message_file.name

        try:
            exit_code = self.module.main(
                ["--message-file", message_path],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: dummy_opener,
            )
        finally:
            os.unlink(message_path)

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            json.loads(dummy_opener.request.data.decode("utf-8"))["rich_message"]["markdown"],
            "message from file\n",
        )

    def test_main_uses_caption_file_for_media_delivery(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 13}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return DummyResponse()

        opener = DummyOpener()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        with tempfile.NamedTemporaryFile("w", delete=False) as caption_file:
            caption_file.write("caption from file\n")
            caption_path = caption_file.name

        try:
            exit_code = self.module.main(
                ["--photo", photo_path, "--caption-file", caption_path],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.unlink(caption_path)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(opener.requests), 1)
        self.assertIn("caption from file", opener.requests[0].data.decode("utf-8", errors="replace"))

    def test_main_sends_caption_only_media_without_empty_followup(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return DummyResponse(b'{"ok": true, "result": {"message_id": 10}}')

        opener = DummyOpener()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                ["--photo", photo_path, "--caption", "inline image smoke check"],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(opener.requests), 1)
        self.assertIn("/botenv-token/sendPhoto", opener.requests[0].full_url)

    def test_main_falls_back_to_link_for_oversized_document(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return DummyResponse(b'{"ok": true, "result": {"message_id": 7}}')

        opener = DummyOpener()
        stdout = io.StringIO()
        old_env = os.environ.copy()
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                [
                    "--file",
                    "/tmp/huge.tar",
                    "--fallback-link",
                    "https://example.com/huge.tar",
                    "--json-output",
                    "artifact too large",
                ],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                stdin_is_tty=True,
                path_exists=lambda path: True,
                stat_fn=lambda path: type("DummyStat", (), {"st_size": 60 * 1024 * 1024})(),
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["fallback_sent"])
        self.assertEqual(result["method"], "sendRichMessage")

    def test_main_errors_for_missing_explicit_local_media_path(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            ["--photo", "/tmp/missing.png", "hello"],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
            path_exists=lambda path: False,
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("does not exist", stderr.getvalue().lower())

    def test_main_errors_for_missing_bare_filename_media_path(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            ["--file", "report", "hello"],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
            path_exists=lambda path: False,
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("does not exist", stderr.getvalue().lower())

    def test_main_errors_for_missing_long_filename_media_path(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            ["--file", "ABCDEFGHIJKLMNOPQRSTUVWX", "hello"],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
            path_exists=lambda path: False,
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("does not exist", stderr.getvalue().lower())

    def test_main_errors_for_missing_long_underscored_filename_media_path(self):
        stderr = io.StringIO()
        exit_code = self.module.main(
            ["--file", "this_is_a_very_long_local_filename_with_underscores_12345", "hello"],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
            path_exists=lambda path: False,
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("does not exist", stderr.getvalue().lower())

    def test_main_allows_explicit_file_id_prefix(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            ["--file", "file_id:ABCDEFGHIJKLMNOPQRSTUVWX", "--dry-run", "--json-output"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=True,
            path_exists=lambda path: False,
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["method"], "sendDocument")
        self.assertFalse(result["sent"])

    def test_main_falls_back_to_link_after_media_send_failure(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []
                self.responses = [
                    DummyResponse(b'{"ok": false, "description": "Bad Request: failed to send"}'),
                    DummyResponse(b'{"ok": true, "result": {"message_id": 8}}'),
                ]

            def open(self, request, timeout=None):
                self.requests.append(request)
                return self.responses.pop(0)

        opener = DummyOpener()
        stdout = io.StringIO()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False) as artifact:
            artifact.write(b"ZIPDATA")
            artifact_path = artifact.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                [
                    "--file",
                    artifact_path,
                    "--fallback-link",
                    "https://example.com/logs.zip",
                    "--json-output",
                    "artifact upload failed",
                ],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                stdin_is_tty=True,
                path_exists=lambda path: True,
                stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(artifact_path)
            os.environ.clear()
            os.environ.update(old_env)

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["fallback_sent"])
        self.assertEqual(result["method"], "sendRichMessage")
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("/botenv-token/sendDocument", opener.requests[0].full_url)
        self.assertIn("/botenv-token/sendRichMessage", opener.requests[1].full_url)
        self.assertIn("https://example.com/logs.zip", opener.requests[1].data.decode("utf-8"))

    def test_main_preserves_caption_in_fallback_message(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []
                self.responses = [
                    DummyResponse(b'{"ok": false, "description": "Bad Request: failed to send"}'),
                    DummyResponse(b'{"ok": true, "result": {"message_id": 11}}'),
                ]

            def open(self, request, timeout=None):
                self.requests.append(request)
                return self.responses.pop(0)

        opener = DummyOpener()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                [
                    "--photo",
                    photo_path,
                    "--caption",
                    "inline image smoke check",
                    "--fallback-link",
                    "https://example.com/photo.png",
                    "--json-output",
                ],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 0)
        self.assertIn("inline image smoke check", opener.requests[1].data.decode("utf-8"))
        self.assertIn("https://example.com/photo.png", opener.requests[1].data.decode("utf-8"))

    def test_main_chunks_long_fallback_message_after_media_send_failure(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                if len(self.requests) == 1:
                    return DummyResponse(b'{"ok": false, "description": "Bad Request: failed to send"}')
                return DummyResponse(b'{"ok": true, "result": {"message_id": 9}}')

        opener = DummyOpener()
        stdout = io.StringIO()
        long_message = "x" * 20000
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".zip", delete=False) as artifact:
            artifact.write(b"ZIPDATA")
            artifact_path = artifact.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                [
                    "--file",
                    artifact_path,
                    "--fallback-link",
                    "https://example.com/huge.log",
                    "--json-output",
                    long_message,
                ],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                stdin_is_tty=True,
                path_exists=lambda path: True,
                stat_fn=lambda path: type("DummyStat", (), {"st_size": 1024})(),
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(artifact_path)
            os.environ.clear()
            os.environ.update(old_env)

        result = json.loads(stdout.getvalue())
        send_message_requests = [
            request for request in opener.requests if request.full_url.endswith("/sendRichMessage")
        ]
        payloads = [json.loads(request.data.decode("utf-8")) for request in send_message_requests]
        texts = [payload["rich_message"]["markdown"] for payload in payloads]

        self.assertEqual(exit_code, 0)
        self.assertTrue(result["fallback_sent"])
        self.assertGreater(len(send_message_requests), 1)
        self.assertTrue(all(len(text) <= self.module.TELEGRAM_RICH_MESSAGE_LIMIT for text in texts))
        self.assertIn("https://example.com/huge.log", "".join(texts))

    def test_main_uses_env_overrides(self):
        class DummyResponse:
            def read(self):
                return b'{"ok": true, "result": {"message_id": 2}}'

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout=None):
                self.request = request
                return DummyResponse()

        dummy_opener = DummyOpener()

        def opener_factory(proxy_url):
            self.assertEqual(proxy_url, "http://127.0.0.1:19090")
            return dummy_opener

        stdout = io.StringIO()
        stderr = io.StringIO()
        old_env = os.environ.copy()
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            os.environ["TELEGRAM_PROXY_URL"] = "http://127.0.0.1:19090"
            exit_code = self.module.main(
                ["hello"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=stderr,
                stdin_is_tty=True,
                opener_factory=opener_factory,
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("/botenv-token/sendRichMessage", dummy_opener.request.full_url)
        self.assertEqual(dummy_opener.request.data, b'{"chat_id":"999","rich_message":{"markdown":"hello"}}')


class RichModeTests(unittest.TestCase):
    def setUp(self):
        self.module = notify_cli
        self.parser = self.module.build_parser()

    def parse(self, argv):
        return self.parser.parse_args(argv)

    def test_default_mode_is_rich_markdown(self):
        self.assertEqual(self.module.resolve_mode(self.parse(["hello"])), "markdown")
        self.assertEqual(self.module.resolve_mode(self.parse(["--plain", "hello"])), "plain")
        self.assertEqual(self.module.resolve_mode(self.parse(["--html", "hello"])), "html")
        self.assertEqual(self.module.resolve_mode(self.parse(["--markdownv2", "hello"])), "markdownv2")
        self.assertEqual(self.module.resolve_mode(self.parse(["--markdown", "hello"])), "markdown")

    def test_rich_and_legacy_flags_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self.parse(["--markdown", "--html", "hello"])
        with self.assertRaises(SystemExit):
            self.parse(["--plain", "--markdownv2", "hello"])

    def test_build_payload_wraps_markdown_in_rich_message(self):
        args = self.parse(["| a | b |"])
        payload = self.module.build_payload("123", args, "| a | b |", "markdown")
        self.assertEqual(payload, {"chat_id": "123", "rich_message": {"markdown": "| a | b |"}})

    def test_build_payload_uses_link_preview_options(self):
        args = self.parse(["--disable-web-preview", "hello"])
        rich = self.module.build_payload("123", args, "hello", "markdown")
        plain = self.module.build_payload("123", args, "hello", "plain")
        self.assertEqual(rich["link_preview_options"], {"is_disabled": True})
        self.assertEqual(plain["link_preview_options"], {"is_disabled": True})
        self.assertNotIn("disable_web_page_preview", rich)
        self.assertNotIn("disable_web_page_preview", plain)

    def test_json_parse_mode_accepts_markdown_and_rich(self):
        for value in ("markdown", "rich", "Markdown", None):
            self.assertEqual(self.module.normalize_parse_mode(value), "markdown")
        self.assertEqual(self.module.normalize_parse_mode("plain"), "plain")
        self.assertEqual(self.module.normalize_parse_mode("html"), "html")
        self.assertEqual(self.module.normalize_parse_mode("markdownv2"), "markdownv2")

    def test_build_text_body_escapes_header_for_legacy_modes(self):
        args = self.parse(["--html", "--title", "<Deploy> & Co", "--tag", "a<b", "body"])
        html_body = self.module.build_text_body(args, "body", None, "html")
        self.assertIn("<b>&lt;Deploy&gt; &amp; Co</b>", html_body)
        self.assertIn("Tags: a&lt;b", html_body)

        args = self.parse(["--markdownv2", "--title", "v1.2!", "body"])
        md2_body = self.module.build_text_body(args, "body", None, "markdownv2")
        self.assertIn("*v1\\.2\\!*", md2_body)

    def test_build_text_body_bold_title_in_markdown_mode(self):
        args = self.parse(["--title", "Deploy", "body"])
        body = self.module.build_text_body(args, "body", None, "markdown")
        self.assertTrue(body.startswith("**Deploy**\n\n"))

    def test_format_quote_block_uses_fenced_code_for_markdown_mode(self):
        block = self.module.format_quote_block("line1\nline2", "markdown")
        self.assertEqual(block, "```\nline1\nline2\n```")

    def test_compute_upload_timeout_scales_with_size(self):
        args = self.parse(["--timeout", "20", "hello"])
        self.assertEqual(self.module.compute_upload_timeout(args, 0), 30)
        self.assertGreater(self.module.compute_upload_timeout(args, 50 * 1024 * 1024), 700)
        args = self.parse(["--timeout", "20", "--upload-timeout", "77", "hello"])
        self.assertEqual(self.module.compute_upload_timeout(args, 50 * 1024 * 1024), 77)

    def test_main_degrades_rich_to_plain_when_method_unsupported(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                if request.full_url.endswith("/sendRichMessage"):
                    raise urllib.error.HTTPError(
                        request.full_url, 404, "Not Found", hdrs=None, fp=io.BytesIO(b"")
                    )
                return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

        opener = DummyOpener()
        stdout = io.StringIO()
        old_env = os.environ.copy()
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            exit_code = self.module.main(
                ["--json-output", "hello"],
                stdin=io.StringIO(""),
                stdout=stdout,
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["degraded_to_plain"])
        self.assertEqual(result["method"], "sendMessage")
        self.assertIn("/sendRichMessage", opener.requests[0].full_url)
        self.assertIn("/sendMessage", opener.requests[1].full_url)
        self.assertEqual(
            json.loads(opener.requests[1].data.decode("utf-8"))["text"], "hello"
        )

    def test_main_dry_run_prints_text_requests_without_json_output(self):
        stdout = io.StringIO()
        exit_code = self.module.main(
            ["--dry-run", "# Report\n\n| a | b |"],
            stdin=io.StringIO(""),
            stdout=stdout,
            stderr=io.StringIO(),
            stdin_is_tty=True,
            opener_factory=lambda proxy_url: self.fail("network should not be used"),
        )

        preview = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertFalse(preview["sent"])
        self.assertEqual(preview["method"], "sendRichMessage")
        self.assertEqual(len(preview["requests"]), 1)
        self.assertEqual(
            preview["requests"][0]["payload"]["rich_message"]["markdown"],
            "# Report\n\n| a | b |",
        )

    def test_main_long_caption_followup_respects_message_limit(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

        opener = DummyOpener()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            exit_code = self.module.main(
                ["--photo", photo_path, "--caption", "c" * 3000],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(opener.requests), 2)
        self.assertIn("/sendPhoto", opener.requests[0].full_url)
        self.assertIn("/sendRichMessage", opener.requests[1].full_url)
        followup = json.loads(opener.requests[1].data.decode("utf-8"))
        self.assertEqual(followup["rich_message"]["markdown"], "c" * (3000 - 1024))

    def test_main_markdown_mode_does_not_stuff_text_into_caption(self):
        class DummyResponse:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        class DummyOpener:
            def __init__(self):
                self.requests = []

            def open(self, request, timeout=None):
                self.requests.append(request)
                return DummyResponse(b'{"ok": true, "result": {"message_id": 1}}')

        opener = DummyOpener()
        old_env = os.environ.copy()
        with tempfile.NamedTemporaryFile("wb", suffix=".png", delete=False) as photo_file:
            photo_file.write(b"PNGDATA")
            photo_path = photo_file.name
        try:
            os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
            os.environ["TELEGRAM_CHAT_ID"] = "999"
            exit_code = self.module.main(
                ["--photo", photo_path, "short **md** body"],
                stdin=io.StringIO(""),
                stdout=io.StringIO(),
                stderr=io.StringIO(),
                stdin_is_tty=True,
                opener_factory=lambda proxy_url: opener,
            )
        finally:
            os.unlink(photo_path)
            os.environ.clear()
            os.environ.update(old_env)

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(opener.requests), 2)
        self.assertNotIn(b'name="caption"', opener.requests[0].data)
        self.assertIn("/sendRichMessage", opener.requests[1].full_url)
        followup = json.loads(opener.requests[1].data.decode("utf-8"))
        self.assertEqual(followup["rich_message"]["markdown"], "short **md** body")


class InstallerAndSkillTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = MODULE_DIR

    def run_script(self, script_name, extra_env=None):
        env = os.environ.copy()
        temp_home = tempfile.mkdtemp(prefix="notify-installer-home-")
        env["HOME"] = temp_home
        if extra_env:
            env.update(extra_env)
        script_path = self.repo_root / "scripts" / script_name
        result = subprocess.run(
            ["bash", str(script_path)],
            cwd=self.repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return temp_home, result

    def test_repo_contains_agent_install_assets(self):
        expected_files = [
            self.repo_root / "skills" / "notify-telegram" / "SKILL.md",
            self.repo_root / "scripts" / "install-notify.sh",
            self.repo_root / "scripts" / "install-codex-skill.sh",
            self.repo_root / "scripts" / "install-claude-skill.sh",
            self.repo_root / "prompts" / "agent-self-setup.md",
        ]

        for path in expected_files:
            self.assertTrue(path.exists(), f"missing asset: {path}")

    def test_install_docs_and_helpers_prefer_git_over_gh(self):
        checked_paths = [
            self.repo_root / "scripts" / "lib" / "install-common.sh",
            self.repo_root / "README.md",
            self.repo_root / "prompts" / "agent-self-setup.md",
        ]

        for path in checked_paths:
            content = path.read_text(encoding="utf-8")
            self.assertIn("git", content)
            self.assertNotIn("gh repo clone", content)

    def test_install_notify_script_creates_working_launcher(self):
        temp_home, result = self.run_script("install-notify.sh")

        self.assertEqual(result.returncode, 0, result.stderr)
        launcher_path = Path(temp_home) / ".local" / "bin" / "notify"
        self.assertTrue(launcher_path.exists())
        self.assertTrue(os.access(launcher_path, os.X_OK))

        help_result = subprocess.run(
            [str(launcher_path), "--help"],
            env={**os.environ, "HOME": temp_home},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--json-output", help_result.stdout)

    def test_install_codex_skill_script_copies_skill_to_codex_homes(self):
        temp_home, result = self.run_script("install-codex-skill.sh")

        self.assertEqual(result.returncode, 0, result.stderr)
        primary_skill = Path(temp_home) / ".codex" / "skills" / "notify-telegram" / "SKILL.md"
        compat_skill = Path(temp_home) / ".agents" / "skills" / "notify-telegram" / "SKILL.md"
        repo_skill = self.repo_root / "skills" / "notify-telegram" / "SKILL.md"

        self.assertTrue(primary_skill.exists())
        self.assertTrue(compat_skill.exists())
        self.assertEqual(primary_skill.read_text(encoding="utf-8"), repo_skill.read_text(encoding="utf-8"))
        self.assertEqual(compat_skill.read_text(encoding="utf-8"), repo_skill.read_text(encoding="utf-8"))

    def test_install_claude_skill_script_copies_skill(self):
        temp_home, result = self.run_script("install-claude-skill.sh")

        self.assertEqual(result.returncode, 0, result.stderr)
        installed_skill = Path(temp_home) / ".claude" / "skills" / "notify-telegram" / "SKILL.md"
        repo_skill = self.repo_root / "skills" / "notify-telegram" / "SKILL.md"

        self.assertTrue(installed_skill.exists())
        self.assertEqual(installed_skill.read_text(encoding="utf-8"), repo_skill.read_text(encoding="utf-8"))

    def test_installers_are_idempotent(self):
        temp_home, first = self.run_script("install-codex-skill.sh")
        self.assertEqual(first.returncode, 0, first.stderr)

        second = subprocess.run(
            ["bash", str(self.repo_root / "scripts" / "install-codex-skill.sh")],
            cwd=self.repo_root,
            env={**os.environ, "HOME": temp_home},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertTrue(
            (Path(temp_home) / ".codex" / "skills" / "notify-telegram" / "SKILL.md").exists()
        )


if __name__ == "__main__":
    unittest.main()
