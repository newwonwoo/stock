#!/usr/bin/env python3
"""Focused NjavTV HLS probe using the browser player's own session.

The probe never clicks through protection or bypasses encryption. It observes the
public player, reuses successful manifest/segment responses, and verifies that a
captured media segment contains a playable video stream. A known 8-byte transport
prefix is tested only as a container normalization step.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

from playwright.async_api import Response, async_playwright


URL = "https://njavtv.com/dm44/ko/miad-812-uncensored-leak"
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"
)
HLS_CHECK = """
() => {
  if (window.hls && window.hls.url) return window.hls.url;
  for (const video of document.querySelectorAll('video')) {
    if (video._hls && video._hls.url) return video._hls.url;
    if (video.hls && video.hls.url) return video.hls.url;
  }
  for (const key of Object.keys(window)) {
    try {
      const value = window[key];
      if (value && typeof value === 'object' && typeof value.url === 'string' && value.url.includes('.m3u8')) {
        return value.url;
      }
    } catch (_) {}
  }
  return null;
}
"""
PLAY_VIDEOS = """
() => {
  let count = 0;
  for (const video of document.querySelectorAll('video')) {
    count += 1;
    video.muted = true;
    video.playsInline = true;
    const result = video.play();
    if (result && result.catch) result.catch(() => {});
  }
  return count;
}
"""


@dataclass
class CapturedResource:
    url: str
    status: int
    body: bytes
    content_type: str
    request_headers: dict[str, str]


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def first_entry(text: str) -> str | None:
    return next(
        (
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
        None,
    )


def is_manifest(url: str, content_type: str) -> bool:
    signal = f"{url} {content_type}".lower()
    return ".m3u8" in signal or "mpegurl" in signal


def is_segment(url: str, content_type: str) -> bool:
    parsed = urlsplit(url)
    path = parsed.path.lower()
    media_type = content_type.lower()
    return (
        parsed.netloc.endswith("surrit.com")
        and (
            path.endswith((".ts", ".m4s", ".mp4"))
            or "video/mp2t" in media_type
            or "video/mp4" in media_type
            or "application/octet-stream" in media_type
        )
    )


def replay_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {
        "accept",
        "accept-language",
        "origin",
        "referer",
        "user-agent",
        "sec-fetch-dest",
        "sec-fetch-mode",
        "sec-fetch-site",
    }
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def same_resource(left: str, right: str) -> bool:
    if left == right:
        return True
    left_parts = urlsplit(left)
    right_parts = urlsplit(right)
    return left_parts.netloc == right_parts.netloc and left_parts.path == right_parts.path


async def browser_request(
    context,
    url: str,
    headers: dict[str, str],
    *,
    byte_range: bool = False,
) -> dict[str, Any]:
    request_headers = dict(headers)
    if byte_range:
        request_headers["Range"] = "bytes=0-4194303"
    response = await context.request.get(
        url,
        headers=request_headers,
        timeout=30_000,
        fail_on_status_code=False,
    )
    body = await response.body()
    return {
        "status": response.status,
        "body": body,
        "bytes": len(body),
        "content_type": response.headers.get("content-type", ""),
        "text": "" if byte_range else body[:1_500_000].decode("utf-8", errors="ignore"),
    }


def probe_video_stream(body: bytes) -> tuple[bool, str, int, str | None]:
    attempts = (("none", body), ("strip-8-byte-prefix", body[8:]))
    last_error: str | None = None
    for transform, candidate in attempts:
        if len(candidate) < 188:
            continue
        with tempfile.NamedTemporaryFile(suffix=".ts") as handle:
            handle.write(candidate)
            handle.flush()
            completed = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "json",
                    handle.name,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        if completed.returncode != 0:
            last_error = completed.stderr.strip()[-600:]
            continue
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            last_error = str(error)
            continue
        video_streams = sum(
            1 for item in payload.get("streams", []) if item.get("codec_type") == "video"
        )
        if video_streams > 0:
            return True, transform, video_streams, None
        last_error = "ffprobe found no video stream"
    return False, "none", 0, last_error


async def main_async() -> int:
    output = pathlib.Path(os.environ.get("DAMA_NJAVTV_REPORT", "njavtv-hls-report.json"))
    started = time.monotonic()
    payload: dict[str, Any] = {
        "page": safe_url(URL),
        "navigation": "not-run",
        "hls_detected": False,
        "manifest_valid": False,
        "segment_valid": False,
        "ffprobe": "not-run",
        "encrypted": False,
        "attempts": 0,
        "captured_manifests": 0,
        "captured_segments": 0,
        "detail": None,
    }
    manifests: list[CapturedResource] = []
    segments: list[CapturedResource] = []
    response_tasks: list[asyncio.Task[None]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
                "--autoplay-policy=no-user-gesture-required",
                "--disable-blink-features=AutomationControlled",
                "--mute-audio",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=ANDROID_UA,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            viewport={"width": 412, "height": 915},
            is_mobile=True,
            has_touch=True,
            ignore_https_errors=True,
        )
        page = await context.new_page()

        async def inspect(response: Response) -> None:
            try:
                headers = await response.all_headers()
                content_type = headers.get("content-type", "")
                request_headers = replay_headers(await response.request.all_headers())
                if is_manifest(response.url, content_type):
                    manifests.append(
                        CapturedResource(
                            url=response.url,
                            status=response.status,
                            body=await response.body(),
                            content_type=content_type,
                            request_headers=request_headers,
                        )
                    )
                elif (
                    len(segments) < 8
                    and response.status in range(200, 300)
                    and is_segment(response.url, content_type)
                ):
                    body = await response.body()
                    if 188 <= len(body) <= 25_000_000:
                        segments.append(
                            CapturedResource(
                                url=response.url,
                                status=response.status,
                                body=body,
                                content_type=content_type,
                                request_headers=request_headers,
                            )
                        )
            except Exception:
                return

        def on_response(response: Response) -> None:
            response_tasks.append(asyncio.create_task(inspect(response)))

        page.on("response", on_response)

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=75_000)
            payload["navigation"] = "success"
            hls_url: str | None = None

            for attempt in range(1, 11):
                payload["attempts"] = attempt
                await page.wait_for_timeout(2_000)
                for frame in page.frames:
                    try:
                        value = await frame.evaluate(HLS_CHECK)
                    except Exception:
                        value = None
                    if isinstance(value, str) and value.startswith("http"):
                        hls_url = value
                        break
                if hls_url:
                    break

            if hls_url:
                for frame in page.frames:
                    try:
                        await frame.evaluate(PLAY_VIDEOS)
                    except Exception:
                        pass
                await page.wait_for_timeout(12_000)

            if response_tasks:
                await asyncio.gather(*response_tasks, return_exceptions=True)
            payload["captured_manifests"] = len(manifests)
            payload["captured_segments"] = len(segments)

            if not hls_url:
                payload["detail"] = "window.hls.url was not available after 20 seconds"
            else:
                payload["hls_detected"] = True
                payload["media_host"] = urlsplit(hls_url).netloc
                payload["media_path"] = urlsplit(hls_url).path
                captured = next(
                    (
                        item
                        for item in manifests
                        if same_resource(item.url, hls_url)
                        and item.status in range(200, 300)
                        and b"#EXTM3U" in item.body
                    ),
                    None,
                )
                if captured is None:
                    payload["detail"] = "HLS URL was found but no successful manifest response was captured"
                else:
                    headers = captured.request_headers
                    current_url = captured.url
                    current_text = captured.body.decode("utf-8", errors="ignore")
                    payload["manifest_source"] = "captured-browser-response"
                    payload["manifest_status"] = captured.status
                    payload["manifest_bytes"] = len(captured.body)
                    payload["manifest_content_type"] = captured.content_type
                    payload["manifest_valid"] = "#EXTM3U" in current_text

                    for depth in range(4):
                        payload["encrypted"] = payload["encrypted"] or "#EXT-X-KEY" in current_text
                        if payload["encrypted"]:
                            break
                        entry = first_entry(current_text)
                        if not entry:
                            payload["detail"] = "manifest contains no child playlist or segment"
                            break
                        entry_url = urljoin(current_url, entry)
                        is_child_playlist = (
                            "#EXT-X-STREAM-INF" in current_text
                            or entry.lower().split("?", 1)[0].endswith(".m3u8")
                        )

                        if is_child_playlist:
                            child_capture = next(
                                (
                                    item
                                    for item in manifests
                                    if same_resource(item.url, entry_url)
                                    and item.status in range(200, 300)
                                    and b"#EXTM3U" in item.body
                                ),
                                None,
                            )
                            if child_capture is not None:
                                child_status = child_capture.status
                                child_body = child_capture.body
                                child_text = child_body.decode("utf-8", errors="ignore")
                                headers = child_capture.request_headers
                                payload[f"playlist_{depth + 1}_source"] = "captured-browser-response"
                            else:
                                child = await browser_request(context, entry_url, headers)
                                child_status = child["status"]
                                child_body = child["body"]
                                child_text = child["text"]
                                payload[f"playlist_{depth + 1}_source"] = "captured-headers-request"
                            payload[f"playlist_{depth + 1}_status"] = child_status
                            payload[f"playlist_{depth + 1}_bytes"] = len(child_body)
                            if child_status not in range(200, 300) or "#EXTM3U" not in child_text:
                                payload["detail"] = f"child playlist validation failed: HTTP {child_status}"
                                break
                            current_url = entry_url
                            current_text = child_text
                            continue

                        segment_capture = next(
                            (item for item in segments if same_resource(item.url, entry_url)),
                            None,
                        )
                        if segment_capture is not None:
                            segment_status = segment_capture.status
                            segment_body = segment_capture.body
                            payload["segment_source"] = "captured-browser-response"
                        else:
                            segment = await browser_request(
                                context,
                                entry_url,
                                headers,
                                byte_range=True,
                            )
                            segment_status = segment["status"]
                            segment_body = segment["body"]
                            payload["segment_source"] = "captured-headers-request"

                        payload["segment_host"] = urlsplit(entry_url).netloc
                        payload["segment_path"] = urlsplit(entry_url).path
                        payload["segment_status"] = segment_status
                        payload["segment_bytes"] = len(segment_body)
                        playable, transform, video_streams, error = probe_video_stream(segment_body)
                        payload["segment_transform"] = transform
                        payload["video_streams"] = video_streams
                        payload["ffprobe"] = "success" if playable else "failed"
                        payload["segment_valid"] = (
                            segment_status in range(200, 300)
                            and len(segment_body) > 0
                            and playable
                        )
                        if not payload["segment_valid"]:
                            payload["detail"] = error or f"segment validation failed: HTTP {segment_status}"
                        break
        except Exception as error:
            payload["navigation"] = "failed"
            payload["detail"] = f"{type(error).__name__}: {str(error)[:1200]}"
        finally:
            payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
            await context.close()
            await browser.close()

    payload["passed"] = bool(
        payload["hls_detected"]
        and payload["manifest_valid"]
        and payload["segment_valid"]
        and payload["ffprobe"] == "success"
        and not payload["encrypted"]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
