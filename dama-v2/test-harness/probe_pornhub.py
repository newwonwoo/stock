#!/usr/bin/env python3
"""Focused Pornhub probe with bounded desktop-browser retries.

The probe uses yt-dlp's official PornHub extractor, desktop Chrome request
semantics, and the site's ordinary age-confirmation cookies. It does not bypass
login, geo restrictions, removed content, paywalls, encryption, or DRM.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
from typing import Any


URL = "https://www.pornhub.com/view_video.php?viewkey=69888bb820b6e"
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)
AGE_COOKIES = (
    "age_verified=1; accessAgeDisclaimerPH=1; "
    "accessAgeDisclaimerUK=1; accessPH=1; platform=pc"
)


def run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def base_command() -> list[str]:
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--socket-timeout",
        "30",
        "--retries",
        "1",
        "--extractor-retries",
        "1",
        "--user-agent",
        DESKTOP_UA,
        "--add-header",
        "Accept-Language:en-US,en;q=0.9",
        "--add-header",
        f"Cookie:{AGE_COOKIES}",
    ]


def compact(value: str) -> str:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    return " | ".join(lines[-8:])[:2000]


def classify(text: str) -> str:
    lower = text.lower()
    if "geo" in lower or "unavailable in your country" in lower:
        return "GEO_RESTRICTED"
    if "removed" in lower or "deleted" in lower or "disabled" in lower:
        return "REMOVED_OR_DISABLED"
    if "login" in lower or "sign in" in lower or "redirection detected" in lower:
        return "LOGIN_OR_REDIRECT"
    if "http error 403" in lower or "forbidden" in lower:
        return "HTTP_403"
    if "http error 429" in lower or "too many requests" in lower:
        return "HTTP_429"
    return "EXTRACTION_FAILED"


def extract_info() -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    attempts = (
        ["--impersonate", "chrome"],
        [],
        ["--impersonate", "chrome", "-4"],
    )
    for index, extra in enumerate(attempts, start=1):
        command = base_command() + [
            "--dump-single-json",
            "--no-warnings",
            *extra,
            URL,
        ]
        completed = run(command, timeout=150)
        json_lines = [
            line for line in completed.stdout.splitlines()
            if line.lstrip().startswith("{")
        ]
        if completed.returncode == 0 and json_lines:
            return json.loads(json_lines[-1]), errors
        errors.append(f"attempt {index}: {compact(completed.stderr or completed.stdout)}")
        if index < len(attempts):
            time.sleep(5)
    return None, errors


def choose_format(info: dict[str, Any]) -> dict[str, Any] | None:
    formats = [item for item in info.get("formats", []) if isinstance(item, dict)]
    viable = [
        item for item in formats
        if item.get("url")
        and item.get("vcodec") not in (None, "none")
        and item.get("acodec") not in (None, "none")
    ]
    if not viable:
        return None

    def score(item: dict[str, Any]) -> tuple[int, int, int]:
        height = int(item.get("height") or 0)
        moderate = int(0 < height <= 720)
        protocol = str(item.get("protocol") or "").lower()
        direct = int(protocol.startswith("http") and "m3u8" not in protocol)
        return moderate, direct, min(height, 720)

    return max(viable, key=score)


def download_sample(format_id: str, output: pathlib.Path) -> tuple[pathlib.Path | None, str]:
    command = base_command() + [
        "--impersonate",
        "chrome",
        "--format",
        format_id,
        "--download-sections",
        "*0-12",
        "--force-keyframes-at-cuts",
        "--merge-output-format",
        "mp4",
        "--output",
        str(output),
        URL,
    ]
    completed = run(command, timeout=300)
    if completed.returncode != 0:
        return None, compact(completed.stderr or completed.stdout)
    matches = [
        path for path in output.parent.glob(output.stem + "*")
        if path.is_file() and path.stat().st_size > 0
    ]
    return (max(matches, key=lambda path: path.stat().st_size), "") if matches else (
        None,
        "yt-dlp returned success without an output file",
    )


def ffprobe(path: pathlib.Path) -> tuple[bool, dict[str, Any] | None, str]:
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
        return False, None, compact(completed.stderr or completed.stdout)
    try:
        return True, json.loads(completed.stdout), ""
    except json.JSONDecodeError as error:
        return False, None, str(error)


def main() -> int:
    output_path = pathlib.Path(
        os.environ.get("DAMA_PORNHUB_REPORT", "pornhub-report.json")
    )
    started = time.monotonic()
    report: dict[str, Any] = {
        "extraction": "not-run",
        "sample_download": "not-run",
        "ffprobe": "not-run",
        "format_count": 0,
        "video_streams": 0,
        "audio_streams": 0,
        "sample_bytes": 0,
        "failure_class": None,
        "detail": None,
    }

    info, errors = extract_info()
    if info is None:
        detail = " || ".join(errors)
        report.update(
            extraction="failed",
            failure_class=classify(detail),
            detail=detail,
        )
    else:
        report["extraction"] = "success"
        report["extractor"] = info.get("extractor_key") or info.get("extractor")
        report["format_count"] = len(info.get("formats") or [])
        candidate = choose_format(info)
        if candidate is None:
            report.update(
                sample_download="failed",
                failure_class="NO_MUXED_FORMAT",
                detail="extractor returned no muxed video/audio format",
            )
        else:
            report["format_id"] = candidate.get("format_id")
            report["height"] = candidate.get("height")
            with tempfile.TemporaryDirectory(prefix="dama-pornhub-") as temp:
                target = pathlib.Path(temp) / "sample.mp4"
                downloaded, error = download_sample(str(candidate.get("format_id")), target)
                if downloaded is None:
                    report.update(
                        sample_download="failed",
                        failure_class=classify(error),
                        detail=error,
                    )
                else:
                    report["sample_download"] = "success"
                    report["sample_bytes"] = downloaded.stat().st_size
                    valid, payload, error = ffprobe(downloaded)
                    if not valid or payload is None:
                        report.update(
                            ffprobe="failed",
                            failure_class="INVALID_MEDIA_FILE",
                            detail=error,
                        )
                    else:
                        streams = payload.get("streams") or []
                        report["video_streams"] = sum(
                            item.get("codec_type") == "video" for item in streams
                        )
                        report["audio_streams"] = sum(
                            item.get("codec_type") == "audio" for item in streams
                        )
                        report["duration_seconds"] = float(
                            (payload.get("format") or {}).get("duration") or 0
                        )
                        report["ffprobe"] = "success"

    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    report["passed"] = bool(
        report["extraction"] == "success"
        and report["sample_download"] == "success"
        and report["ffprobe"] == "success"
        and report["video_streams"] > 0
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
