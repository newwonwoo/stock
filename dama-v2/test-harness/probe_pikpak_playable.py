#!/usr/bin/env python3
"""Run the public PikPak share probe with playable-media validation."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from urllib.parse import urlsplit

import probe_pikpak_share as base


async def validate_playable_link(
    context,
    link: str,
    source_key: str,
    page_url: str,
) -> base.LinkCandidate:
    parsed = urlsplit(link)
    candidate = base.LinkCandidate(
        host=parsed.netloc,
        path=parsed.path,
        source_key=source_key,
    )
    try:
        response = await context.request.get(
            link,
            headers={
                "Referer": page_url,
                "Range": "bytes=0-8388607",
            },
            timeout=45_000,
            fail_on_status_code=False,
        )
        body = await response.body()
        candidate.status = response.status
        candidate.bytes_received = len(body)
        candidate.content_type = response.headers.get("content-type")
        if response.status not in range(200, 300) and response.status != 206:
            candidate.validation = "failed"
            candidate.detail = f"HTTP {response.status}"
            return candidate
        if not body:
            candidate.validation = "failed"
            candidate.detail = "zero-byte response"
            return candidate

        with tempfile.NamedTemporaryFile(suffix=".mp4") as handle:
            handle.write(body)
            handle.flush()
            completed = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-probesize",
                    "8388608",
                    "-analyzeduration",
                    "10000000",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "json",
                    handle.name,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
            )
        if completed.returncode != 0:
            candidate.validation = "failed"
            candidate.detail = "ffprobe: " + completed.stderr.strip()[-500:]
            return candidate
        payload = json.loads(completed.stdout)
        video_streams = sum(
            item.get("codec_type") == "video"
            for item in payload.get("streams", [])
        )
        if video_streams < 1:
            candidate.validation = "failed"
            candidate.detail = "ffprobe found no video stream"
            return candidate

        candidate.validation = "success"
        candidate.detail = f"ffprobe video_streams={video_streams}"
        return candidate
    except Exception as error:
        candidate.validation = "failed"
        candidate.detail = f"{type(error).__name__}: {str(error)[:500]}"
        return candidate


def main() -> int:
    base.validate_link = validate_playable_link
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
