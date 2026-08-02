#!/usr/bin/env python3
"""Focused NjavTV HLS.js probe using the browser player's own session.

The page is observed without clicking because NjavTV currently creates its HLS
instance during initialization and clicks can navigate away from the player.
The probe first reuses an actual successful browser response. If no body was
captured, it fetches inside the same iframe so cookies, Origin, and Referer match
the player session. It does not bypass encryption or DRM.
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

from playwright.async_api import Frame, Response, async_playwright


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

FRAME_FETCH_TEXT = """
async ({url, range}) => {
  const headers = range ? {Range: range} : {};
  const response = await fetch(url, {
    method: 'GET',
    credentials: 'include',
    cache: 'no-store',
    headers
  });
  const buffer = await response.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  const limit = Math.min(bytes.length, 1500000);
  let text = '';
  if (!range) {
    text = new TextDecoder('utf-8').decode(bytes.slice(0, limit));
  }
  return {
    status: response.status,
    bytes: bytes.length,
    text,
    contentType: response.headers.get('content-type') || ''
  };
}
"""


@dataclass
class CapturedResponse:
    url: str
    status: int
    body: bytes
    content_type: str
    frame_url: str
    request_headers: dict[str, str]


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def first_playlist_entry(text: str) -> str | None:
    return next(
        (
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ),
        None,
    )


def is_manifest_response(url: str, content_type: str) -> bool:
    signal = f"{url} {content_type}".lower()
    return ".m3u8" in signal or "mpegurl" in signal


def filtered_request_headers(headers: dict[str, str]) -> dict[str, str]:
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


async def frame_fetch(
    frame: Frame,
    url: str,
    *,
    range_header: str | None = None,
) -> dict[str, Any]:
    return await frame.evaluate(
        FRAME_FETCH_TEXT,
        {"url": url, "range": range_header},
    )


async def request_fetch(
    context,
    url: str,
    *,
    headers: dict[str, str],
    range_header: str | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers)
    if range_header:
        request_headers["Range"] = range_header
    response = await context.request.get(
        url,
        headers=request_headers,
        timeout=30_000,
        fail_on_status_code=False,
    )
    body = await response.body()
    response_headers = await response.all_headers()
    return {
        "status": response.status,
        "bytes": len(body),
        "text": body[:1_500_000].decode("utf-8", errors="ignore") if not range_header else "",
        "contentType": response_headers.get("content-type", ""),
    }


async def main_async() -> int:
    output = pathlib.Path(os.environ.get("DAMA_NJAVTV_REPORT", "njavtv-hls-report.json"))
    started = time.monotonic()
    payload: dict[str, Any] = {
        "page": safe_url(URL),
        "navigation": "not-run",
        "hls_detected": False,
        "manifest_source": None,
        "manifest_valid": False,
        "segment_source": None,
        "segment_valid": False,
        "encrypted": False,
        "attempts": 0,
        "captured_manifests": 0,
        "detail": None,
    }
    response_tasks: list[asyncio.Task[None]] = []
    captured_manifests: list[CapturedResponse] = []

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

        async def inspect_response(response: Response) -> None:
            try:
                response_headers = await response.all_headers()
                content_type = response_headers.get("content-type", "")
                if not is_manifest_response(response.url, content_type):
                    return
                body = await response.body()
                request_headers = await response.request.all_headers()
                frame_url = response.request.frame.url
                captured_manifests.append(
                    CapturedResponse(
                        url=response.url,
                        status=response.status,
                        body=body,
                        content_type=content_type,
                        frame_url=frame_url,
                        request_headers=filtered_request_headers(request_headers),
                    )
                )
            except Exception:
                return

        def on_response(response: Response) -> None:
            response_tasks.append(asyncio.create_task(inspect_response(response)))

        page.on("response", on_response)

        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=75_000)
            payload["navigation"] = "success"
            hls_url: str | None = None
            hls_frame: Frame | None = None

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
                        hls_frame = frame
                        break
                if hls_url:
                    break

            if response_tasks:
                await asyncio.gather(*response_tasks, return_exceptions=True)
            payload["captured_manifests"] = len(captured_manifests)

            if not hls_url or hls_frame is None:
                payload["detail"] = "window.hls.url was not available after 20 seconds"
            else:
                payload["hls_detected"] = True
                payload["media_host"] = urlsplit(hls_url).netloc
                payload["media_path"] = urlsplit(hls_url).path
                payload["player_frame"] = safe_url(hls_frame.url)

                manifest_result: dict[str, Any] | None = None
                matching_capture = next(
                    (
                        item
                        for item in captured_manifests
                        if item.url == hls_url
                        and item.status in range(200, 300)
                        and b"#EXTM3U" in item.body
                    ),
                    None,
                )
                request_headers: dict[str, str] = {}

                if matching_capture is not None:
                    manifest_result = {
                        "status": matching_capture.status,
                        "bytes": len(matching_capture.body),
                        "text": matching_capture.body.decode("utf-8", errors="ignore"),
                        "contentType": matching_capture.content_type,
                    }
                    request_headers = matching_capture.request_headers
                    payload["manifest_source"] = "captured-browser-response"
                else:
                    try:
                        manifest_result = await frame_fetch(hls_frame, hls_url)
                        payload["manifest_source"] = "same-frame-fetch"
                    except Exception as frame_error:
                        closest_capture = next(
                            (item for item in captured_manifests if item.url == hls_url),
                            None,
                        )
                        request_headers = (
                            closest_capture.request_headers
                            if closest_capture is not None
                            else {
                                "Referer": hls_frame.url,
                                "Origin": f"{urlsplit(hls_frame.url).scheme}://{urlsplit(hls_frame.url).netloc}",
                                "User-Agent": ANDROID_UA,
                            }
                        )
                        try:
                            manifest_result = await request_fetch(
                                context,
                                hls_url,
                                headers=request_headers,
                            )
                            payload["manifest_source"] = "captured-headers-request"
                        except Exception as request_error:
                            payload["detail"] = (
                                f"frame fetch: {type(frame_error).__name__}: {str(frame_error)[:350]} | "
                                f"header replay: {type(request_error).__name__}: {str(request_error)[:350]}"
                            )

                if manifest_result is not None:
                    text = str(manifest_result.get("text") or "")
                    payload["manifest_status"] = manifest_result.get("status")
                    payload["manifest_bytes"] = manifest_result.get("bytes")
                    payload["manifest_content_type"] = manifest_result.get("contentType")
                    payload["manifest_valid"] = (
                        int(manifest_result.get("status") or 0) in range(200, 300)
                        and "#EXTM3U" in text
                    )
                    payload["encrypted"] = "#EXT-X-KEY" in text

                    current_url = hls_url
                    current_text = text
                    # Resolve a master playlist once before selecting a media segment.
                    first_entry = first_playlist_entry(current_text)
                    if (
                        payload["manifest_valid"]
                        and first_entry
                        and ("#EXT-X-STREAM-INF" in current_text or first_entry.lower().endswith(".m3u8"))
                    ):
                        child_url = urljoin(current_url, first_entry)
                        try:
                            child = await frame_fetch(hls_frame, child_url)
                            child_text = str(child.get("text") or "")
                            if int(child.get("status") or 0) in range(200, 300) and "#EXTM3U" in child_text:
                                current_url = child_url
                                current_text = child_text
                                payload["media_playlist_source"] = "same-frame-fetch"
                                payload["media_playlist_bytes"] = child.get("bytes")
                                payload["encrypted"] = payload["encrypted"] or "#EXT-X-KEY" in child_text
                        except Exception:
                            pass

                    segment = first_playlist_entry(current_text)
                    if payload["manifest_valid"] and not payload["encrypted"] and segment:
                        segment_url = urljoin(current_url, segment)
                        try:
                            segment_result = await frame_fetch(
                                hls_frame,
                                segment_url,
                                range_header="bytes=0-1048575",
                            )
                            payload["segment_source"] = "same-frame-fetch"
                        except Exception as frame_segment_error:
                            if not request_headers:
                                request_headers = {
                                    "Referer": hls_frame.url,
                                    "Origin": f"{urlsplit(hls_frame.url).scheme}://{urlsplit(hls_frame.url).netloc}",
                                    "User-Agent": ANDROID_UA,
                                }
                            try:
                                segment_result = await request_fetch(
                                    context,
                                    segment_url,
                                    headers=request_headers,
                                    range_header="bytes=0-1048575",
                                )
                                payload["segment_source"] = "captured-headers-request"
                            except Exception as request_segment_error:
                                segment_result = None
                                payload["detail"] = (
                                    f"segment frame fetch: {type(frame_segment_error).__name__}: "
                                    f"{str(frame_segment_error)[:300]} | replay: "
                                    f"{type(request_segment_error).__name__}: {str(request_segment_error)[:300]}"
                                )

                        if segment_result is not None:
                            payload["segment_host"] = urlsplit(segment_url).netloc
                            payload["segment_path"] = urlsplit(segment_url).path
                            payload["segment_status"] = segment_result.get("status")
                            payload["segment_bytes"] = segment_result.get("bytes")
                            payload["segment_valid"] = (
                                int(segment_result.get("status") or 0) in range(200, 300)
                                and int(segment_result.get("bytes") or 0) > 0
                            )
        except Exception as error:
            payload["navigation"] = "failed"
            payload["detail"] = f"{type(error).__name__}: {str(error)[:1200]}"
        finally:
            payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
            await context.close()
            await browser.close()

    passed = bool(
        payload["hls_detected"]
        and payload["manifest_valid"]
        and payload["segment_valid"]
        and not payload["encrypted"]
    )
    payload["passed"] = passed
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if passed else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
