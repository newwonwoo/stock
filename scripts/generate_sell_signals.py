"""
실시간 sell_signals 파이프라인.

흐름:
  1. DART 일별 공시 fetch (오늘만)
  2. 22타입 분류 → SELL_TRIGGER 만 필터
  3. 봇 universe (corp_code → stock_code 역매핑) 안 종목만
  4. 중복 가드 (.cache/sell_signals_processed.json)
  5. 신규 시그널만 HMAC 서명 후 out/sell_signals_<id>.json 으로 박제

봇 측에서 consume 후 processed/ 로 mv. 본 스크립트는 같은 signal_id 재발행 X.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any

from src import config
from src.analyzers.disclosure_classifier import classify
from src.analyzers.sell_signal_generator import generate as make_sell_signal
from src.utils.kst_time import fmt_compact, today_kst
from src.utils.logger import get_logger

log = get_logger("sell_pipe")

SIGNED_BY = "research_v1"
OUT_DIR = config.ROOT_DIR / "out"
PROCESSED_FILE = config.CACHE_DIR / "sell_signals_processed.json"


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _wrap(data: dict, key: str) -> dict:
    return {
        "signed_by": SIGNED_BY,
        "sha256_hmac": hmac.new(key.encode(), _canonical(data), hashlib.sha256).hexdigest(),
        "data": data,
    }


def _load_processed() -> set[str]:
    if not PROCESSED_FILE.exists():
        return set()
    try:
        return set(json.loads(PROCESSED_FILE.read_text()))
    except Exception:
        return set()


def _save_processed(ids: set[str]) -> None:
    PROCESSED_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROCESSED_FILE.write_text(json.dumps(sorted(ids), ensure_ascii=False))


def main() -> int:
    key = os.environ.get("RESEARCH_HMAC_KEY", "")
    if not key:
        log.info("RESEARCH_HMAC_KEY 미설정 — 종료")
        return 1
    if not config.DART_API_KEY:
        log.info("DART_API_KEY 미설정 — 종료")
        return 1

    from src.collectors.dart_corp_cache import load_or_refresh
    from src.collectors.dart_fetcher import DartFetcher

    fetcher = DartFetcher()
    corp_map = load_or_refresh(fetcher)
    # corp_code → stock_code 역매핑 (corp_code 가 키, listed 만 포함)
    corp_to_stock = {v: k for k, v in corp_map.items()}

    today = today_kst()
    today_compact = fmt_compact(today)

    disclosures = fetcher.fetch_daily_disclosures(today_compact)
    log.info(f"disclosures fetched: {len(disclosures)}")

    processed = _load_processed()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new_count = 0

    for d in disclosures:
        report_nm = d.get("report_nm") or ""
        cd = classify(report_nm)
        if cd is None or cd.effect != "SELL_TRIGGER":
            continue

        corp_code = d.get("corp_code") or ""
        stock_code = corp_to_stock.get(corp_code)
        if not stock_code:
            # 비상장은 skip
            continue

        rcept_no = d.get("rcept_no")
        rcept_dt = d.get("rcept_dt")
        sig = make_sell_signal(
            code=stock_code,
            name=d.get("corp_name") or "",
            classified=cd,
            rcept_no=rcept_no,
            rcept_dt=rcept_dt,
        )
        if not sig:
            continue
        if sig["signal_id"] in processed:
            continue

        path = OUT_DIR / f"sell_signal_{sig['signal_id']}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(_wrap(sig, key), f, ensure_ascii=False, indent=2)
            f.write("\n")
        log.info(f"new sell_signal: {sig['signal_id']} {stock_code} {cd.type_code} {cd.severity}")
        processed.add(sig["signal_id"])
        new_count += 1

    _save_processed(processed)
    log.info(f"done: new={new_count} total_processed={len(processed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
