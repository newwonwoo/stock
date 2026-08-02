#!/usr/bin/env python3
"""Focused NjavTV HLS.js probe based on the site's current player behavior."""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import time
from urllib.parse import urljoin, urlsplit

from playwright.async_api import async_playwright


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


async def main_async() -> int:
    output = pathlib.Path(os.environ.get("DAMA_NJAVTV_REPORT", "njavtv-hls-report.json"))
    started = time.monotonic()
    payload: dict[str, object] = {
        "page": f"{urlsplit(URL).scheme}://{urlsplit(URL).netloc}{urlsplit(URL).path}",
        "navigation": "not-run",
        "hls_detected": False,
        "manifest_valid": False,
        "segment_valid": False,
        "encrypted": False,
        "attempts": 0,
        "detail": None,
    }

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

            if not hls_url:
                payload["detail"] = "window.hls.url was not available after 20 seconds"
            else:
                payload["hls_detected"] = True
                payload["media_host"] = urlsplit(hls_url).netloc
                response = await context.request.get(
                    hls_url,
                    headers={"Referer": page.url},
                    timeout=30_000,
                    fail_on_status_code=False,
                )
                body = await response.body()
                text = body.decode("utf-8", errors="ignore")
                payload["manifest_status"] = response.status
                payload["manifest_bytes"] = len(body)
                payload["manifest_valid"] = response.status in range(200, 300) and "#EXTM3U" in text
                payload["encrypted"] = "#EXT-X-KEY" in text

                if payload["manifest_valid"] and not payload["encrypted"]:
                    segment = next(
                        (
                            line.strip()
                            for line in text.splitlines()
                            if line.strip() and not line.startswith("#")
                        ),
                        None,
                    )
                    if segment:
                        segment_response = await context.request.get(
                            urljoin(hls_url, segment),
                            headers={
                                "Referer": page.url,
                                "Range": "bytes=0-1048575",
                            },
                            timeout=30_000,
                            fail_on_status_code=False,
                        )
                        segment_body = await segment_response.body()
                        payload["segment_status"] = segment_response.status
                        payload["segment_bytes"] = len(segment_body)
                        payload["segment_valid"] = (
                            segment_response.status in range(200, 300)
                            and len(segment_body) > 0
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
