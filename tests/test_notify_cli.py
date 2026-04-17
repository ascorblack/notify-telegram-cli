import json
import io
import os
import sys
import unittest
import tempfile
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

    def test_media_flags_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            self.parse(["--photo", "a.png", "--file", "b.zip"])

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
                "--json",
                "--dry-run",
            ]
        )
        self.assertEqual(args.attach, "artifact.png")
        self.assertEqual(args.title, "Deploy finished")
        self.assertEqual(args.tag, ["deploy", "success"])
        self.assertEqual(args.link, ["https://example.com/run/123"])
        self.assertTrue(args.json)
        self.assertTrue(args.dry_run)

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
                ["--quote", quote_path, "hello"],
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

        self.assertEqual(request.full_url, "https://api.telegram.org/bottoken/sendPhoto")
        self.assertIn("multipart/form-data", request.get_header("Content-type"))
        self.assertIn("photo", request.data.decode("utf-8", errors="replace"))
        self.assertIn("PNGDATA", request.data.decode("utf-8", errors="replace"))

    def test_help_mentions_html_markdown_proxy_and_stdin(self):
        help_text = self.parser.format_help()
        self.assertIn("--html", help_text)
        self.assertIn("--markdownv2", help_text)
        self.assertIn("stdin", help_text.lower())
        self.assertIn("proxy", help_text.lower())

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

    def test_main_rejects_media_invocation_until_implemented(self):
        class DummyOpener:
            def open(self, request, timeout=None):
                raise AssertionError("opener should not be used for unimplemented media")

        stderr = io.StringIO()
        exit_code = self.module.main(
            ["--photo", "a.png", "hello"],
            stdin=io.StringIO(""),
            stdout=io.StringIO(),
            stderr=stderr,
            stdin_is_tty=True,
            opener_factory=lambda proxy_url: DummyOpener(),
        )

        self.assertEqual(exit_code, 2)
        self.assertIn("media delivery is not implemented yet", stderr.getvalue().lower())

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
        self.assertIn("/botenv-token/sendMessage", dummy_opener.request.full_url)
        self.assertEqual(dummy_opener.request.data, b'{"chat_id":"999","text":"hello"}')


if __name__ == "__main__":
    unittest.main()
