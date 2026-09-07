#!/usr/bin/env python3
"""Headless-browser fallback probe for Dama's three real target pages.

This only observes requests made by the public page and validates non-DRM media
candidates. It does not bypass login, paywalls, encryption, or DRM.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import time
from dataclasses import asdict, dataclass
from urllib.parse import urljoin, urlsplit

from playwright.async_api import BrowserContext, Page, Response, async_playwright


TARGETS = {
    "pikpak": "https://mypikpak.com/s/VNzIoP3OOM7_uDGdjnL-1jfto1/AAAMZ1xW5Ojbaa8a8D4ttRDEo1_VNz",
    "njavtv": "https://njavtv.com/dm44/ko/miad-812-uncensored-leak",
    "pornhub": "https://www.pornhub.com/view_video.php?viewkey=69888bb820b6e",
}

ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"
)

MEDIA_RE = re.compile(
    r"https?://[^\s\"'<>\\]+?(?:\.m3u8|\.mpd|\.mp4|\.webm|\.m4v|\.mov|\.m4s|\.ts)(?:\?[^\s\"'<>\\]*)?",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    url: str
    kind: str
    source: str
    content_type: str | None = None
    status: int | None = None
    validation: str = "not-run"
    bytes_received: int = 0
    detail: str | None = None


@dataclass
class BrowserResult:
    site: str
    page: str
    navigation: str = "not-run"
    final_page: str | None = None
    title_present: bool = False
    video_elements: int = 0
    network_responses: int = 0
    media_candidates: int = 0
    validated_candidates: int = 0
    drm_signal: bool = False
    failure_class: str | None = None
    detail: str | None = None
    elapsed_seconds: float = 0.0
    candidates: list[dict] | None = None


def safe_url(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def classify_kind(url: str, content_type: str | None) -> str:
    signal = f"{url} {content_type or ''}".lower()
    if ".m3u8" in signal or "mpegurl" in signal:
        return "HLS"
    if ".mpd" in signal or "dash+xml" in signal:
        return "DASH"
    if "widevine" in signal or "license" in signal or "drm" in signal:
        return "DRM_SIGNAL"
    if ".m4s" in signal:
        return "MSE_FRAGMENT"
    if ".ts" in signal or "video/mp2t" in signal:
        return "HLS_SEGMENT"
    return "DIRECT"


def media_like(url: str, content_type: str | None, resource_type: str) -> bool:
    lower_url = url.lower()
    lower_type = (content_type or "").lower()
    return (
        resource_type == "media"
        or lower_type.startswith("video/")
        or lower_type.startswith("audio/")
        or "mpegurl" in lower_type
        or "dash+xml" in lower_type
        or any(ext in lower_url for ext in (".m3u8", ".mpd", ".mp4", ".webm", ".m4v", ".mov", ".m4s", ".ts"))
    )


def candidate_key(candidate: Candidate) -> tuple[str, str]:
    return candidate.url, candidate.kind


async def add_candidate(
    candidates: dict[tuple[str, str], Candidate],
    url: str,
    source: str,
    content_type: str | None = None,
    status: int | None = None,
) -> None:
    if not url or url.startswith("blob:") or url.startswith("data:"):
        return
    kind = classify_kind(url, content_type)
    candidate = Candidate(
        url=url,
        kind=kind,
        source=source,
        content_type=content_type,
        status=status,
    )
    candidates.setdefault(candidate_key(candidate), candidate)


async def inspect_json_response(
    response: Response,
    candidates: dict[tuple[str, str], Candidate],
) -> None:
    headers = await response.all_headers()
    content_type = headers.get("content-type", "")
    length_text = headers.get("content-length", "0").split(";", 1)[0]
    try:
        length = int(length_text)
    except ValueError:
        length = 0
    if "json" not in content_type.lower() or length > 2_000_000:
        return
    try:
        text = await response.text()
    except Exception:
        return
    for match in MEDIA_RE.findall(text.replace("\\/", "/")):
        await add_candidate(candidates, match, "json-response", content_type)


async def dismiss_overlays(page: Page) -> None:
    labels = [
        "Accept",
        "Accept all",
        "I agree",
        "I am 18 or older",
        "Enter",
        "Continue",
        "동의",
        "모두 동의",
        "확인",
        "입장",
    ]
    for label in labels:
        try:
            locator = page.get_by_text(label, exact=False).first
            if await locator.is_visible(timeout=700):
                await locator.click(timeout=1500)
                await page.wait_for_timeout(500)
        except Exception:
            pass


async def stimulate_playback(page: Page) -> int:
    count = 0
    for frame in page.frames:
        try:
            count += await frame.locator("video").count()
            await frame.locator("video").evaluate_all(
                """videos => videos.forEach(video => {
                    video.muted = true;
                    video.playsInline = true;
                    const result = video.play();
                    if (result && result.catch) result.catch(() => {});
                })"""
            )
        except Exception:
            pass

        for selector in (
            ".vjs-big-play-button",
            ".jw-icon-playback",
            ".plyr__control--overlaid",
            "button[aria-label*='Play' i]",
            "button[title*='Play' i]",
            "video",
        ):
            try:
                locator = frame.locator(selector).first
                if await locator.is_visible(timeout=500):
                    await locator.click(force=True, timeout=1200)
            except Exception:
                pass
    return count


async def collect_dom_sources(
    page: Page,
    candidates: dict[tuple[str, str], Candidate],
) -> None:
    for frame in page.frames:
        try:
            sources = await frame.locator("video, audio, source").evaluate_all(
                """nodes => nodes.flatMap(node => [
                    node.currentSrc || '',
                    node.src || '',
                    node.getAttribute('src') || ''
                ]).filter(Boolean)"""
            )
        except Exception:
            continue
        for source in sources:
            await add_candidate(candidates, urljoin(frame.url, source), "dom-media")


async def validate_candidate(
    context: BrowserContext,
    page_url: str,
    candidate: Candidate,
) -> None:
    if candidate.kind == "DRM_SIGNAL":
        candidate.validation = "blocked"
        candidate.detail = "DRM/license signal; no bypass attempted"
        return
    try:
        headers = {
            "Referer": page_url,
            "Origin": f"{urlsplit(page_url).scheme}://{urlsplit(page_url).netloc}",
        }
        if candidate.kind in {"DIRECT", "MSE_FRAGMENT", "HLS_SEGMENT"}:
            headers["Range"] = "bytes=0-1048575"
        response = await context.request.get(
            candidate.url,
            headers=headers,
            timeout=30_000,
            fail_on_status_code=False,
        )
        body = await response.body()
        candidate.status = response.status
        candidate.bytes_received = len(body)
        if response.status not in range(200, 300) and response.status != 206:
            candidate.validation = "failed"
            candidate.detail = f"HTTP {response.status}"
            return

        if candidate.kind == "HLS":
            text = body[:1_000_000].decode("utf-8", errors="ignore")
            if "#EXT-X-KEY" in text:
                candidate.validation = "blocked"
                candidate.detail = "encrypted HLS detected"
                return
            if "#EXTM3U" not in text:
                candidate.validation = "failed"
                candidate.detail = "response is not an HLS manifest"
                return
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
                    urljoin(candidate.url, segment),
                    headers={**headers, "Range": "bytes=0-1048575"},
                    timeout=30_000,
                    fail_on_status_code=False,
                )
                segment_body = await segment_response.body()
                candidate.bytes_received += len(segment_body)
                if segment_response.status not in range(200, 300) and segment_response.status != 206:
                    candidate.validation = "failed"
                    candidate.detail = f"manifest ok; segment HTTP {segment_response.status}"
                    return
        elif candidate.kind == "DASH":
            text = body[:1_000_000].decode("utf-8", errors="ignore")
            if "<ContentProtection" in text or "widevine" in text.lower():
                candidate.validation = "blocked"
                candidate.detail = "DRM-protected DASH detected"
                return
            if "<MPD" not in text:
                candidate.validation = "failed"
                candidate.detail = "response is not a DASH manifest"
                return

        candidate.validation = "success" if candidate.bytes_received > 0 else "failed"
        if candidate.bytes_received <= 0:
            candidate.detail = "zero-byte response"
    except Exception as error:
        candidate.validation = "failed"
        candidate.detail = f"{type(error).__name__}: {str(error)[:500]}"


async def probe_target(
    browser,
    site: str,
    url: str,
) -> BrowserResult:
    started = time.monotonic()
    result = BrowserResult(site=site, page=safe_url(url))
    context = await browser.new_context(
        user_agent=ANDROID_UA,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        viewport={"width": 412, "height": 915},
        device_scale_factor=2.625,
        is_mobile=True,
        has_touch=True,
        ignore_https_errors=True,
    )
    page = await context.new_page()
    candidates: dict[tuple[str, str], Candidate] = {}
    response_count = 0
    drm_signal = False

    async def on_response(response: Response) -> None:
        nonlocal response_count, drm_signal
        response_count += 1
        try:
            headers = await response.all_headers()
        except Exception:
            headers = {}
        content_type = headers.get("content-type")
        request = response.request
        if any(term in response.url.lower() for term in ("widevine", "license", "drm")):
            drm_signal = True
        if media_like(response.url, content_type, request.resource_type):
            await add_candidate(
                candidates,
                response.url,
                f"network:{request.resource_type}",
                content_type,
                response.status,
            )
        if request.resource_type in {"xhr", "fetch"}:
            await inspect_json_response(response, candidates)

    page.on("response", on_response)

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=75_000)
        result.navigation = "success"
        await dismiss_overlays(page)
        result.video_elements = await stimulate_playback(page)
        for _ in range(4):
            await page.wait_for_timeout(5_000)
            await collect_dom_sources(page, candidates)
            await stimulate_playback(page)
        result.final_page = safe_url(page.url)
        result.title_present = bool((await page.title()).strip())
    except Exception as error:
        result.navigation = "failed"
        result.failure_class = "BROWSER_NAVIGATION_FAILED"
        result.detail = f"{type(error).__name__}: {str(error)[:1200]}"
    finally:
        result.network_responses = response_count
        result.drm_signal = drm_signal

    ranked = sorted(
        candidates.values(),
        key=lambda item: (
            item.kind not in {"DIRECT", "HLS", "DASH"},
            item.kind != "DIRECT",
            item.source,
        ),
    )[:20]
    for candidate in ranked:
        await validate_candidate(context, page.url, candidate)

    result.media_candidates = len(ranked)
    result.validated_candidates = sum(
        1 for item in ranked if item.validation == "success"
    )
    if result.validated_candidates == 0 and result.failure_class is None:
        if drm_signal or any(item.validation == "blocked" for item in ranked):
            result.failure_class = "DRM_OR_ENCRYPTED"
        elif result.video_elements > 0:
            result.failure_class = "PLAYER_FOUND_NO_DOWNLOADABLE_REQUEST"
        else:
            result.failure_class = "NO_MEDIA_REQUEST_FOUND"
    result.candidates = [
        {
            **asdict(item),
            "url": safe_url(item.url),
        }
        for item in ranked
    ]
    result.elapsed_seconds = round(time.monotonic() - started, 2)
    await context.close()
    return result


async def async_main() -> int:
    output = pathlib.Path(
        os.environ.get("DAMA_BROWSER_REPORT", "browser-target-report.json")
    )
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
        try:
            results = [
                await probe_target(browser, site, url)
                for site, url in TARGETS.items()
            ]
        finally:
            await browser.close()

    payload = {
        "generated_at_epoch": int(time.time()),
        "all_detected": all(item.validated_candidates > 0 for item in results),
        "results": [asdict(item) for item in results],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["all_detected"] else 1


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
