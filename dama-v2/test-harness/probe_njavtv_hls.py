#!/usr/bin/env python3
"""Focused NjavTV HLS probe using the browser player's own session.

The page creates its HLS instance during initialization. The probe does not click
or bypass encryption. It captures the manifest response and its request headers,
then validates child playlists and one media segment with the same browser
cookies and headers.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
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


@dataclass
class CapturedManifest:
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


async def browser_request(
    context,
    url: str,
    headers: dict[str, str],
    *,
    byte_range: bool = False,
) -> dict[str, Any]:
    request_headers = dict(headers)
    if byte_range:
        request_headers["Range"] = "bytes=0-1048575"
    response = await context.request.get(
        url,
        headers=request_headers,
        timeout=30_000,
        fail_on_status_code=False,
    )
    body = await response.body()
    return {
        "status": response.status,
        "bytes": len(body),
        "content_type": response.headers.get("content-type", ""),
        "text": "" if byte_range else body[:1_500_000].decode("utf-8", errors="ignore"),
    }


async def main_async() -> int:
    output = pathlib.Path(os.environ.get("DAMA_NJAVTV_REPORT", "njavtv-hls-report.json"))
    started = time.monotonic()
    payload: dict[str, Any] = {
        "page": safe_url(URL),
        "navigation": "not-run",
        "hls_detected": False,
        "manifest_valid": False,
        "segment_valid": False,
        "encrypted": False,
        "attempts": 0,
        "captured_manifests": 0,
        "detail": None,
    }
    captures: list[CapturedManifest] = []
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
                if not is_manifest(response.url, content_type):
                    return
                captures.append(
                    CapturedManifest(
                        url=response.url,
                        status=response.status,
                        body=await response.body(),
                        content_type=content_type,
                        request_headers=replay_headers(await response.request.all_headers()),
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

            if response_tasks:
                await asyncio.gather(*response_tasks, return_exceptions=True)
            payload["captured_manifests"] = len(captures)

            if not hls_url:
                payload["detail"] = "window.hls.url was not available after 20 seconds"
            else:
                payload["hls_detected"] = True
                payload["media_host"] = urlsplit(hls_url).netloc
                payload["media_path"] = urlsplit(hls_url).path
                captured = next(
                    (
                        item
                        for item in captures
                        if item.url == hls_url
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

                    for depth in range(3):
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
                            child = await browser_request(context, entry_url, headers)
                            payload[f"playlist_{depth + 1}_status"] = child["status"]
                            payload[f"playlist_{depth + 1}_bytes"] = child["bytes"]
                            if child["status"] not in range(200, 300) or "#EXTM3U" not in child["text"]:
                                payload["detail"] = f"child playlist validation failed: HTTP {child['status']}"
                                break
                            current_url = entry_url
                            current_text = child["text"]
                            continue

                        segment = await browser_request(
                            context,
                            entry_url,
                            headers,
                            byte_range=True,
                        )
                        payload["segment_host"] = urlsplit(entry_url).netloc
                        payload["segment_path"] = urlsplit(entry_url).path
                        payload["segment_status"] = segment["status"]
                        payload["segment_bytes"] = segment["bytes"]
                        payload["segment_valid"] = (
                            segment["status"] in range(200, 300)
                            and segment["bytes"] > 0
                        )
                        if not payload["segment_valid"]:
                            payload["detail"] = f"segment validation failed: HTTP {segment['status']}"
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
