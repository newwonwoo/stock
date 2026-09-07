#!/usr/bin/env python3
"""Probe the user's real Dama MVP target URLs.

The probe deliberately does not bypass authentication, paywalls, encryption, or DRM.
It tries yt-dlp extraction, downloads a short playable sample when possible, validates
it with ffprobe, and writes one compact JSON report containing no signed media URLs.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, asdict
from urllib.parse import urlsplit


TARGETS = {
    "pikpak": "https://mypikpak.com/s/VNzIoP3OOM7_uDGdjnL-1jfto1/AAAMZ1xW5Ojbaa8a8D4ttRDEo1_VNz",
    "njavtv": "https://njavtv.com/dm44/ko/miad-812-uncensored-leak",
    "pornhub": "https://www.pornhub.com/view_video.php?viewkey=69888bb820b6e",
}

ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36"
)


@dataclass
class SiteResult:
    site: str
    page: str
    extraction: str = "not-run"
    extractor: str | None = None
    format_count: int = 0
    candidate_kind: str | None = None
    candidate_format_id: str | None = None
    sample_download: str = "not-run"
    sample_bytes: int = 0
    ffprobe: str = "not-run"
    video_streams: int = 0
    audio_streams: int = 0
    duration_seconds: float | None = None
    failure_class: str | None = None
    detail: str | None = None
    elapsed_seconds: float = 0.0


def safe_page(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )


def classify_failure(text: str) -> str:
    value = text.lower()
    if "drm" in value or "encrypted" in value:
        return "DRM_OR_ENCRYPTED"
    if "sign in" in value or "login" in value or "authentication" in value:
        return "LOGIN_REQUIRED"
    if "cookie" in value:
        return "COOKIE_REQUIRED"
    if "http error 403" in value or "forbidden" in value:
        return "HTTP_403"
    if "http error 429" in value or "too many requests" in value:
        return "HTTP_429"
    if "connection reset" in value or "errno 104" in value:
        return "NETWORK_RESET"
    if "unsupported url" in value:
        return "UNSUPPORTED_URL"
    if "unable to download webpage" in value:
        return "PAGE_DOWNLOAD_FAILED"
    if "no video formats" in value or "requested format is not available" in value:
        return "NO_FORMATS"
    return "EXTRACTION_FAILED"


def compact_detail(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return " | ".join(lines[-6:])[:1600]


def yt_dlp_base(url: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--socket-timeout",
        "20",
        "--retries",
        "0",
        "--extractor-retries",
        "0",
        "--user-agent",
        ANDROID_UA,
        "--add-header",
        "Accept-Language:ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        url,
    ]


def extract_info(url: str) -> tuple[dict | None, str]:
    attempts = [
        ["--dump-single-json", "--no-warnings"],
        ["--dump-single-json", "--no-warnings", "--impersonate", "chrome"],
        ["--dump-single-json", "--no-warnings", "-4"],
    ]
    errors: list[str] = []
    for options in attempts:
        command = yt_dlp_base(url)
        command[3:3] = options
        completed = run(command, timeout=120)
        json_lines = [
            line for line in completed.stdout.splitlines() if line.lstrip().startswith("{")
        ]
        if completed.returncode == 0 and json_lines:
            return json.loads(json_lines[-1]), ""
        errors.append(compact_detail(completed.stderr or completed.stdout))
    return None, " || ".join(errors)


def select_candidate(info: dict) -> dict | None:
    formats = [item for item in info.get("formats", []) if isinstance(item, dict)]
    if not formats and info.get("url"):
        return {
            "format_id": info.get("format_id") or "fallback",
            "url": info.get("url"),
            "protocol": info.get("protocol"),
            "ext": info.get("ext"),
            "vcodec": info.get("vcodec"),
            "acodec": info.get("acodec"),
            "height": info.get("height") or 0,
        }

    def score(item: dict) -> tuple[int, int, int, int]:
        vcodec = item.get("vcodec")
        acodec = item.get("acodec")
        muxed = int(vcodec not in (None, "none") and acodec not in (None, "none"))
        progressive = int(str(item.get("protocol", "")).startswith("http"))
        mp4 = int(item.get("ext") in {"mp4", "m4v"})
        height = int(item.get("height") or 0)
        return muxed, progressive, mp4, -height

    viable = [item for item in formats if item.get("url")]
    return max(viable, key=score) if viable else None


def candidate_kind(candidate: dict) -> str:
    protocol = str(candidate.get("protocol") or "").lower()
    url = str(candidate.get("url") or "").lower()
    if "m3u8" in protocol or ".m3u8" in url:
        return "HLS"
    if "dash" in protocol or ".mpd" in url:
        return "DASH"
    return "DIRECT"


def download_sample(url: str, format_id: str, output: pathlib.Path) -> tuple[bool, str]:
    command = yt_dlp_base(url)
    command[3:3] = [
        "--no-warnings",
        "--format",
        format_id,
        "--download-sections",
        "*0-12",
        "--force-keyframes-at-cuts",
        "--merge-output-format",
        "mp4",
        "--output",
        str(output),
    ]
    completed = run(command, timeout=240)
    if completed.returncode != 0:
        return False, compact_detail(completed.stderr or completed.stdout)

    matches = sorted(output.parent.glob(output.stem + "*"))
    valid = [path for path in matches if path.is_file() and path.stat().st_size > 0]
    if not valid:
        return False, "yt-dlp returned success but no output file was created"
    chosen = max(valid, key=lambda path: path.stat().st_size)
    if chosen != output:
        shutil.move(str(chosen), str(output))
    return True, ""


def probe_file(path: pathlib.Path) -> tuple[bool, dict | None, str]:
    completed = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        timeout=60,
    )
    if completed.returncode != 0:
        return False, None, compact_detail(completed.stderr or completed.stdout)
    try:
        return True, json.loads(completed.stdout), ""
    except json.JSONDecodeError as error:
        return False, None, f"invalid ffprobe json: {error}"


def probe_site(site: str, url: str, workdir: pathlib.Path) -> SiteResult:
    started = time.monotonic()
    result = SiteResult(site=site, page=safe_page(url))
    info, error = extract_info(url)
    if info is None:
        result.extraction = "failed"
        result.failure_class = classify_failure(error)
        result.detail = error
        result.elapsed_seconds = round(time.monotonic() - started, 2)
        return result

    result.extraction = "success"
    result.extractor = str(info.get("extractor_key") or info.get("extractor") or "unknown")
    result.format_count = len(info.get("formats") or [])
    candidate = select_candidate(info)
    if candidate is None:
        result.sample_download = "failed"
        result.failure_class = "NO_DOWNLOADABLE_CANDIDATE"
        result.detail = "extractor returned no candidate URL"
        result.elapsed_seconds = round(time.monotonic() - started, 2)
        return result

    result.candidate_kind = candidate_kind(candidate)
    result.candidate_format_id = str(candidate.get("format_id") or "fallback")
    output = workdir / f"{site}.mp4"
    ok, error = download_sample(url, result.candidate_format_id, output)
    if not ok:
        result.sample_download = "failed"
        result.failure_class = classify_failure(error)
        result.detail = error
        result.elapsed_seconds = round(time.monotonic() - started, 2)
        return result

    result.sample_download = "success"
    result.sample_bytes = output.stat().st_size
    valid, payload, error = probe_file(output)
    if not valid or payload is None:
        result.ffprobe = "failed"
        result.failure_class = "INVALID_MEDIA_FILE"
        result.detail = error
        result.elapsed_seconds = round(time.monotonic() - started, 2)
        return result

    result.ffprobe = "success"
    streams = payload.get("streams") or []
    result.video_streams = sum(1 for item in streams if item.get("codec_type") == "video")
    result.audio_streams = sum(1 for item in streams if item.get("codec_type") == "audio")
    duration = (payload.get("format") or {}).get("duration")
    result.duration_seconds = round(float(duration), 3) if duration else None
    if result.video_streams < 1:
        result.failure_class = "NO_VIDEO_STREAM"
        result.detail = "downloaded sample does not contain a video stream"
    result.elapsed_seconds = round(time.monotonic() - started, 2)
    return result


def main() -> int:
    output_path = pathlib.Path(os.environ.get("DAMA_TARGET_REPORT", "target-site-report.json"))
    with tempfile.TemporaryDirectory(prefix="dama-targets-") as temp:
        workdir = pathlib.Path(temp)
        results = [probe_site(site, url, workdir) for site, url in TARGETS.items()]

    payload = {
        "generated_at_epoch": int(time.time()),
        "all_passed": all(
            item.extraction == "success"
            and item.sample_download == "success"
            and item.ffprobe == "success"
            and item.video_streams > 0
            for item in results
        ),
        "results": [asdict(item) for item in results],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
