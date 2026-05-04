"""환경변수 로딩 + 시스템 상수."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUT_DIR = ROOT_DIR / "out"
CACHE_DIR = ROOT_DIR / ".cache"

MARKET_CAP_MIN: int = 500_000_000_000  # 5천억 KRW

DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_DAILY_LIMIT = 10_000

DART_API_KEY = os.environ.get("DART_API_KEY", "")
KIS_APP_KEY = os.environ.get("KIS_APP_KEY", "")
KIS_APP_SECRET = os.environ.get("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.environ.get("KIS_ACCOUNT_NO", "")
TELEGRAM_API_ID = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
TELEGRAM_SESSION = os.environ.get("TELEGRAM_SESSION", "")
RESEARCH_HMAC_KEY = os.environ.get("RESEARCH_HMAC_KEY", "")


def require(name: str) -> str:
    val = os.environ.get(name, "")
    if not val:
        raise RuntimeError(f"환경변수 {name} 미설정")
    return val
