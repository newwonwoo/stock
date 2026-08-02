#!/usr/bin/env python3
"""Focused probe for a public PikPak share link.

The probe observes only requests initiated by the public share page. It does not
use account credentials, bypass a passcode, or reproduce private client secrets.
It extracts public file metadata/download links, validates a bounded byte range,
and writes a redacted JSON report.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import time
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, Response, async_playwright


SHARE_URL = "https://mypikpak.com/s/VNzIoP3OOM7_uDGdjnL-1jfto1/AAAMZ1xW5Ojbaa8a8D4ttRDEo1_VNz"
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"
)
API_HOSTS = {"api-drive.mypikpak.net", "user.mypikpak.net"}
MEDIA_EXTENSIONS = (".mp4", ".mkv", ".webm", ".mov", ".m4v", ".m3u8", ".mpd")
URL_KEYS = {
    "web_content_link",
    "webContentLink",
    "download_url",
    "downloadUrl",
    "content_link",
    "contentLink",
    "streaming_url",
    "streamingUrl",
    "url",
}
ID_KEYS = {"id", "file_id", "fileId"}


@dataclass
class LinkCandidate:
    host: str
    path: str
    source_key: str
    status: int | None = None
    bytes_received: int = 0
    content_type: str | None = None
    validation: str = "not-run"
    detail: str | None = None


@dataclass
class PikPakResult:
    page: str
    navigation: str = "not-run"
    final_page: str | None = None
    api_responses: int = 0
    parsed_json_responses: int = 0
    file_ids: int = 0
    media_files: int = 0
    link_candidates: int = 0
    validated_links: int = 0
    login_required: bool = False
    passcode_required: bool = False
    failure_class: str | None = None
    detail: str | None = None
    elapsed_seconds: float = 0.0
    candidates: list[dict[str, Any]] | None = None


def safe_page(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def is_http_url(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def looks_media_url(value: str) -> bool:
    lower = value.lower()
    return any(ext in lower for ext in MEDIA_EXTENSIONS) or any(
        token in lower for token in ("download", "stream", "transcode", "media")
    )


def looks_media_file(node: dict[str, Any]) -> bool:
    name = str(node.get("name") or node.get("file_name") or "").lower()
    mime = str(node.get("mime_type") or node.get("mimeType") or "").lower()
    kind = str(node.get("kind") or node.get("type") or "").lower()
    return (
        any(name.endswith(ext) for ext in MEDIA_EXTENSIONS)
        or mime.startswith("video/")
        or kind in {"video", "media"}
    )


def walk_json(
    node: Any,
    *,
    path: str = "$",
    file_ids: set[str],
    media_files: list[dict[str, Any]],
    raw_links: list[tuple[str, str]],
) -> None:
    if isinstance(node, dict):
        if looks_media_file(node):
            media_files.append(
                {
                    "name": str(node.get("name") or node.get("file_name") or "")[:180],
                    "id": str(node.get("id") or node.get("file_id") or "")[:180],
                    "mime": str(node.get("mime_type") or node.get("mimeType") or "")[:100],
                    "size": node.get("size"),
                }
            )
        for key, value in node.items():
            current = f"{path}.{key}"
            if key in ID_KEYS and isinstance(value, str) and value:
                file_ids.add(value)
            if key in URL_KEYS and is_http_url(value) and looks_media_url(value):
                raw_links.append((value, current))
            walk_json(
                value,
                path=current,
                file_ids=file_ids,
                media_files=media_files,
                raw_links=raw_links,
            )
    elif isinstance(node, list):
        for index, item in enumerate(node):
            walk_json(
                item,
                path=f"{path}[{index}]",
                file_ids=file_ids,
                media_files=media_files,
                raw_links=raw_links,
            )


def select_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {
        "accept",
        "accept-language",
        "content-type",
        "origin",
        "referer",
        "user-agent",
        "x-client-id",
        "x-device-id",
        "x-captcha-token",
    }
    return {key: value for key, value in headers.items() if key.lower() in allowed}


async def click_public_preview(page: Page) -> None:
    selectors = (
        "video",
        "button[aria-label*='play' i]",
        "button[title*='play' i]",
        "[class*='play' i]",
        "[class*='file' i]",
        "[class*='video' i]",
    )
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if await locator.is_visible(timeout=800):
                await locator.click(force=True, timeout=1500)
                await page.wait_for_timeout(800)
        except Exception:
            pass


async def validate_link(
    context: BrowserContext,
    link: str,
    source_key: str,
    page_url: str,
) -> LinkCandidate:
    parsed = urlsplit(link)
    candidate = LinkCandidate(
        host=parsed.netloc,
        path=parsed.path,
        source_key=source_key,
    )
    try:
        response = await context.request.get(
            link,
            headers={
                "Referer": page_url,
                "Range": "bytes=0-1048575",
            },
            timeout=30_000,
            fail_on_status_code=False,
        )
        body = await response.body()
        headers = await response.all_headers()
        candidate.status = response.status
        candidate.bytes_received = len(body)
        candidate.content_type = headers.get("content-type")
        if response.status in range(200, 300) or response.status == 206:
            candidate.validation = "success" if body else "failed"
            if not body:
                candidate.detail = "zero-byte response"
        else:
            candidate.validation = "failed"
            candidate.detail = f"HTTP {response.status}"
    except Exception as error:
        candidate.validation = "failed"
        candidate.detail = f"{type(error).__name__}: {str(error)[:500]}"
    return candidate


async def main_async() -> int:
    output = pathlib.Path(os.environ.get("DAMA_PIKPAK_REPORT", "pikpak-share-report.json"))
    started = time.monotonic()
    result = PikPakResult(page=safe_page(SHARE_URL))
    file_ids: set[str] = set()
    media_files: list[dict[str, Any]] = []
    raw_links: list[tuple[str, str]] = []
    api_headers: dict[str, str] = {}
    api_responses = 0
    parsed_json = 0
    response_tasks: list[asyncio.Task[None]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=[
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
            nonlocal api_responses, parsed_json, api_headers
            parsed = urlsplit(response.url)
            if parsed.netloc not in API_HOSTS and "/drive/v1/share" not in parsed.path:
                return
            api_responses += 1
            try:
                request_headers = await response.request.all_headers()
                if not api_headers:
                    api_headers = select_headers(request_headers)
                headers = await response.all_headers()
                content_type = headers.get("content-type", "")
                if "json" not in content_type.lower():
                    return
                payload = await response.json()
                parsed_json += 1
                serialized = json.dumps(payload, ensure_ascii=False).lower()
                if "pass_code_empty" in serialized or "passcode" in serialized:
                    result.passcode_required = True
                if "login" in serialized or "unauthenticated" in serialized:
                    result.login_required = True
                walk_json(
                    payload,
                    file_ids=file_ids,
                    media_files=media_files,
                    raw_links=raw_links,
                )
            except Exception:
                return

        def on_response(response: Response) -> None:
            response_tasks.append(asyncio.create_task(inspect_response(response)))

        page.on("response", on_response)

        try:
            await page.goto(SHARE_URL, wait_until="domcontentloaded", timeout=75_000)
            result.navigation = "success"
            await page.wait_for_timeout(8_000)
            await click_public_preview(page)
            await page.wait_for_timeout(12_000)
            result.final_page = safe_page(page.url)
        except Exception as error:
            result.navigation = "failed"
            result.failure_class = "BROWSER_NAVIGATION_FAILED"
            result.detail = f"{type(error).__name__}: {str(error)[:1200]}"

        if response_tasks:
            await asyncio.gather(*response_tasks, return_exceptions=True)

        # If the page exposed file IDs but not links, repeat the public file_info
        # request with headers observed from the page itself. No hard-coded client
        # credentials or account cookies are introduced here.
        share_parts = [part for part in urlsplit(SHARE_URL).path.split("/") if part]
        share_id = share_parts[1] if len(share_parts) >= 2 and share_parts[0] == "s" else ""
        if share_id and file_ids and api_headers and not raw_links:
            for file_id in list(file_ids)[:10]:
                try:
                    endpoint = (
                        "https://api-drive.mypikpak.net/drive/v1/share/file_info"
                        f"?share_id={share_id}&file_id={file_id}"
                    )
                    response = await context.request.get(
                        endpoint,
                        headers=api_headers,
                        timeout=30_000,
                        fail_on_status_code=False,
                    )
                    headers = await response.all_headers()
                    if response.status in range(200, 300) and "json" in headers.get("content-type", ""):
                        payload = await response.json()
                        parsed_json += 1
                        walk_json(
                            payload,
                            file_ids=file_ids,
                            media_files=media_files,
                            raw_links=raw_links,
                        )
                except Exception:
                    continue

        unique_links: list[tuple[str, str]] = []
        seen_links: set[str] = set()
        for link, source in raw_links:
            if link not in seen_links:
                seen_links.add(link)
                unique_links.append((link, source))

        validated: list[LinkCandidate] = []
        for link, source in unique_links[:10]:
            validated.append(await validate_link(context, link, source, page.url))

        result.api_responses = api_responses
        result.parsed_json_responses = parsed_json
        result.file_ids = len(file_ids)
        result.media_files = len(media_files)
        result.link_candidates = len(unique_links)
        result.validated_links = sum(item.validation == "success" for item in validated)
        result.candidates = [asdict(item) for item in validated]

        if result.validated_links == 0 and result.failure_class is None:
            if result.login_required:
                result.failure_class = "LOGIN_REQUIRED"
            elif result.passcode_required:
                result.failure_class = "PASSCODE_REQUIRED"
            elif api_responses == 0:
                result.failure_class = "NO_PUBLIC_SHARE_API_REQUEST"
            elif parsed_json == 0:
                result.failure_class = "NO_PARSEABLE_SHARE_RESPONSE"
            elif media_files == []:
                result.failure_class = "NO_MEDIA_FILE_IN_SHARE"
            elif not unique_links:
                result.failure_class = "MEDIA_FOUND_NO_PUBLIC_LINK"
            else:
                result.failure_class = "PUBLIC_LINK_VALIDATION_FAILED"

        result.elapsed_seconds = round(time.monotonic() - started, 2)
        await context.close()
        await browser.close()

    payload = {**asdict(result), "passed": result.validated_links > 0}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["passed"] else 1


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
