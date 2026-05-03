"""
DART 종목코드 ↔ corp_code 매핑 캐시.

월 1회 (또는 cache 부재 시) 갱신. .cache/dart_corp_codes.json 박제.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from src import config
from src.collectors.dart_fetcher import DartFetcher
from src.utils.logger import get_logger

log = get_logger("dart_cache")

CACHE_FILE = config.CACHE_DIR / "dart_corp_codes.json"
REFRESH_INTERVAL_SEC = 30 * 24 * 3600  # 30일


def _is_stale(p: Path) -> bool:
    if not p.exists():
        return True
    age = time.time() - p.stat().st_mtime
    return age > REFRESH_INTERVAL_SEC


def load_or_refresh(fetcher: DartFetcher | None = None) -> dict[str, str]:
    """stock_code(6) → corp_code(8) 매핑."""
    if not _is_stale(CACHE_FILE):
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log.info(f"cache load 실패, 재생성: {e}")

    f = fetcher or DartFetcher()
    codes = f.fetch_corp_codes()
    mapping = {c.stock_code: c.corp_code for c in codes if c.stock_code}
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(mapping, ensure_ascii=False))
    log.info(f"corp_code cache refreshed: {len(mapping)} listed tickers → {CACHE_FILE}")
    return mapping
