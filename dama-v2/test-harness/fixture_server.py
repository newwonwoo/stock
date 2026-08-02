#!/usr/bin/env python3
"""Deterministic local HTTP fixtures for Dama v2 extraction tests."""

from __future__ import annotations

import argparse
import socket
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


class FixtureHandler(BaseHTTPRequestHandler):
    server_version = "DamaFixture/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _send(self, status: int, content_type: str, body: bytes, **headers: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        self.wfile.write(body)

    def _absolute(self, path: str) -> str:
        host, port = self.server.server_address
        public_host = "127.0.0.1" if host in {"", "0.0.0.0"} else host
        return f"http://{public_host}:{port}{path}"

    def do_HEAD(self) -> None:
        self.do_GET(send_body=False)

    def do_GET(self, send_body: bool = True) -> None:  # type: ignore[override]
        path = urlparse(self.path).path

        if path == "/health":
            self._send(200, "text/plain; charset=utf-8", b"ok")
            return

        if path == "/page/direct":
            media = self._absolute("/media/sample.mp4")
            body = (
                "<!doctype html><html><head><title>fixture direct</title></head>"
                f"<body><video controls src=\"{media}\"></video></body></html>"
            ).encode()
            self._send(200, "text/html; charset=utf-8", body)
            return

        if path == "/page/hls":
            manifest = self._absolute("/hls/master.m3u8")
            body = (
                "<!doctype html><html><head><title>fixture hls</title></head>"
                f"<body><video controls src=\"{manifest}\"></video></body></html>"
            ).encode()
            self._send(200, "text/html; charset=utf-8", body)
            return

        if path == "/page/dash":
            manifest = self._absolute("/dash/manifest.mpd")
            body = (
                "<!doctype html><html><head><title>fixture dash</title></head>"
                f"<body><video controls src=\"{manifest}\"></video></body></html>"
            ).encode()
            self._send(200, "text/html; charset=utf-8", body)
            return

        if path == "/media/sample.mp4":
            body = b"\x00\x00\x00\x18ftypmp42dama-fixture"
            self._send(200, "video/mp4", body, Accept_Ranges="bytes")
            return

        if path == "/hls/master.m3u8":
            body = (
                "#EXTM3U\n"
                "#EXT-X-VERSION:3\n"
                "#EXT-X-TARGETDURATION:4\n"
                "#EXT-X-MEDIA-SEQUENCE:0\n"
                "#EXTINF:4.0,\n"
                f"{self._absolute('/hls/segment0.ts')}\n"
                "#EXT-X-ENDLIST\n"
            ).encode()
            self._send(200, "application/vnd.apple.mpegurl", body)
            return

        if path == "/hls/segment0.ts":
            self._send(200, "video/mp2t", b"G" + (b"\x00" * 187))
            return

        if path == "/dash/manifest.mpd":
            body = (
                "<?xml version=\"1.0\"?>"
                "<MPD xmlns=\"urn:mpeg:dash:schema:mpd:2011\" type=\"static\" "
                "mediaPresentationDuration=\"PT4S\" minBufferTime=\"PT1S\">"
                "<Period><AdaptationSet mimeType=\"video/mp4\">"
                "<Representation id=\"v1\" bandwidth=\"100000\" width=\"320\" height=\"180\">"
                "<BaseURL>/media/sample.mp4</BaseURL>"
                "</Representation></AdaptationSet></Period></MPD>"
            ).encode()
            self._send(200, "application/dash+xml", body)
            return

        if path == "/status/403":
            self._send(403, "text/plain; charset=utf-8", b"forbidden")
            return

        if path == "/status/429":
            self._send(429, "text/plain; charset=utf-8", b"too many requests", Retry_After="60")
            return

        if path == "/login":
            self._send(
                200,
                "text/html; charset=utf-8",
                b"<html><body>Sign in to continue</body></html>",
            )
            return

        if path == "/cookie-required":
            if "dama_session=fixture" not in self.headers.get("Cookie", ""):
                self._send(403, "text/plain; charset=utf-8", b"cookie required")
                return
            self._send(200, "text/html; charset=utf-8", b"<html><body>cookie ok</body></html>")
            return

        if path == "/reset":
            linger = struct.pack("ii", 1, 0)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
            self.connection.close()
            return

        self._send(404, "text/plain; charset=utf-8", b"not found")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), FixtureHandler)
    print(f"READY http://{args.host}:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
