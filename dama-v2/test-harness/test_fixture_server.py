#!/usr/bin/env python3
"""Host-side integration tests for Dama v2's controlled network fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.client import RemoteDisconnected
from http.server import ThreadingHTTPServer

from fixture_server import FixtureHandler


class FixtureIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def read(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, str, bytes]:
        request = urllib.request.Request(self.base_url + path, headers=headers or {})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.headers.get_content_type(), response.read()

    def test_direct_media_fixture(self) -> None:
        status, content_type, body = self.read("/media/sample.mp4")
        self.assertEqual(200, status)
        self.assertEqual("video/mp4", content_type)
        self.assertTrue(body.startswith(b"\x00\x00\x00\x18ftyp"))

    def test_hls_and_dash_fixtures(self) -> None:
        status, content_type, body = self.read("/hls/master.m3u8")
        self.assertEqual(200, status)
        self.assertIn(content_type, {"application/vnd.apple.mpegurl", "application/x-mpegurl"})
        self.assertIn(b"#EXTM3U", body)
        self.assertIn(b"segment0.ts", body)

        status, content_type, body = self.read("/dash/manifest.mpd")
        self.assertEqual(200, status)
        self.assertEqual("application/dash+xml", content_type)
        self.assertIn(b"<MPD", body)
        self.assertIn(b"sample.mp4", body)

    def test_http_failure_fixtures(self) -> None:
        for path, expected in (("/status/403", 403), ("/status/429", 429)):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.read(path)
            self.assertEqual(expected, caught.exception.code)

    def test_cookie_gate_is_deterministic(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.read("/cookie-required")
        self.assertEqual(403, caught.exception.code)

        status, _, body = self.read(
            "/cookie-required",
            headers={"Cookie": "dama_session=fixture"},
        )
        self.assertEqual(200, status)
        self.assertIn(b"cookie ok", body)

    def test_connection_reset_fixture(self) -> None:
        request = urllib.request.Request(self.base_url + "/reset")
        with self.assertRaises((ConnectionResetError, RemoteDisconnected, urllib.error.URLError)):
            urllib.request.urlopen(request, timeout=5).read()

    def test_yt_dlp_generic_extractor_finds_direct_media(self) -> None:
        command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--no-playlist",
            "--no-warnings",
            "--socket-timeout",
            "5",
            self.base_url + "/page/direct",
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)

        json_lines = [line for line in completed.stdout.splitlines() if line.lstrip().startswith("{")]
        self.assertTrue(json_lines, completed.stdout)
        payload = json.loads(json_lines[-1])

        candidates = [payload.get("url")]
        candidates.extend(
            item.get("url")
            for item in payload.get("formats", [])
            if isinstance(item, dict)
        )
        self.assertTrue(
            any(candidate and "/media/sample.mp4" in candidate for candidate in candidates),
            payload,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
