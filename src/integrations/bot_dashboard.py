"""
TradeBot dashboard 클라이언트. 봇 EC2 의 /api/swing/* GET endpoint 호출.

SWING_INTEGRATION_BOT.md §1.2 spec.

env:
  BOT_DASHBOARD_URL : "http://<EC2_HOST>:5000"  (또는 https://...)
  SWING_API_TOKEN   : 64자 bearer token (봇·리서치 양쪽 동일 secret)
"""

from __future__ import annotations

import os
from typing import Any

import requests

from src.utils.logger import get_logger

log = get_logger("bot_api")

_TIMEOUT = 8


class BotDashboardError(RuntimeError):
    pass


def _config() -> tuple[str, str] | None:
    # GitHub Secrets 가 multi-line 으로 저장된 경우 trailing \n 또는 공백 포함 가능 → strip 필수.
    url = os.environ.get("BOT_DASHBOARD_URL", "").strip().rstrip("/")
    token = os.environ.get("SWING_API_TOKEN", "").strip()
    if not url or not token:
        return None
    return (url, token)


def _get(path: str) -> Any:
    cfg = _config()
    if cfg is None:
        raise BotDashboardError("BOT_DASHBOARD_URL / SWING_API_TOKEN 미설정")
    url, token = cfg
    r = requests.get(
        f"{url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=_TIMEOUT,
    )
    if r.status_code == 401 or r.status_code == 403:
        raise BotDashboardError(f"{path}: 인증 실패 (HTTP {r.status_code})")
    r.raise_for_status()
    return r.json()


def fetch_held_stocks() -> list[dict[str, Any]] | None:
    """현재 보유 종목 list. 미설정/오류 시 None."""
    if _config() is None:
        return None
    try:
        data = _get("/api/swing/held_stocks")
    except Exception as e:
        log.info(f"held_stocks fetch 실패: {e}")
        return None
    if isinstance(data, dict) and "held_stocks" in data:
        return list(data["held_stocks"])
    if isinstance(data, list):
        return data
    return []


def held_stock_codes() -> set[str] | None:
    """보유 종목 코드 set. None 이면 봇 dashboard 사용 불가 (호출자가 fallback)."""
    held = fetch_held_stocks()
    if held is None:
        return None
    out: set[str] = set()
    for h in held:
        c = h.get("code") if isinstance(h, dict) else None
        if c:
            out.add(str(c))
    return out
