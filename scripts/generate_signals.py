"""
End-to-end signal generation pipeline.

흐름:
  1. universe = KRX 시총 ≥5천억 (top N 제한 가능, env UNIVERSE_LIMIT)
  2. 시장 공통 데이터: short_top10, KIS 지수, KRX 시총
  3. 종목별 (universe 순회):
       - KRX OHLCV 60일
       - KRX investor_flow / foreign_ownership
       - 9중 필터 분석 (DART 데이터는 best-effort, 빠지면 skip)
  4. buy_signal_generator → buy_signals_{date}.json (signals 배열)
  5. macro_brief → macro_status_{date}.json
  6. blacklist_active.json (자동 제외 SHORT_TOP10 만 우선)
  7. 모두 HMAC 서명 envelope 으로 out/ 에 기록
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
from src.analyzers import (
    buy_signal_generator,
    credit_short,
    flow_analysis,
    macro_brief,
    technical,
)
from src.collectors import krx_fetcher
from src.utils.kst_time import fmt_date, today_kst
from src.utils.logger import get_logger

log = get_logger("pipeline")
SIGNED_BY = "research_v1"
OUT_DIR = config.ROOT_DIR / "out"


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _wrap(data: dict, key: str) -> dict:
    return {
        "signed_by": SIGNED_BY,
        "sha256_hmac": hmac.new(key.encode(), _canonical(data), hashlib.sha256).hexdigest(),
        "data": data,
    }


def _write_signed(path: Path, data: dict, key: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(_wrap(data, key), f, ensure_ascii=False, indent=2)
        f.write("\n")
    log.info(f"wrote {path}")


def _telegram_messages() -> list[dict[str, Any]]:
    p = OUT_DIR / "telegram_messages.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _kis_indices_safe() -> dict[str, Any]:
    if not (config.KIS_APP_KEY and config.KIS_APP_SECRET):
        return {}
    try:
        from src.collectors.kis_fetcher import KisFetcher
        return KisFetcher().fetch_market_indices()
    except Exception as e:
        log.info(f"KIS indices skip: {e}")
        return {}


def _index_change(idx: dict[str, dict[str, Any]], name: str) -> float:
    p = idx.get(name) or {}
    val = p.get("bstp_nmix_prdy_ctrt") or p.get("prdy_ctrt") or 0
    try:
        return float(val)
    except Exception:
        return 0.0


def main() -> int:
    key = os.environ.get("RESEARCH_HMAC_KEY", "")
    if not key:
        log.info("RESEARCH_HMAC_KEY 미설정 — 종료")
        return 1

    universe_limit = int(os.environ.get("UNIVERSE_LIMIT", "30"))

    today_str = fmt_date(today_kst())

    # 1. universe + 시장 데이터
    universe = krx_fetcher.fetch_universe_by_market_cap()
    universe.sort(key=lambda t: t.market_cap, reverse=True)
    universe = universe[:universe_limit]
    log.info(f"universe limited to top {len(universe)} by market cap")

    short_top = krx_fetcher.fetch_short_top10()
    short_top_codes = {it["code"] for items in short_top.values() for it in items}

    tg_msgs = _telegram_messages()

    # 2. 종목별 분석
    signals: list[dict[str, Any]] = []
    for t in universe:
        try:
            ohlcv = krx_fetcher.fetch_ohlcv(t.code, days=80)
        except Exception as e:
            log.info(f"{t.code} OHLCV 실패 skip: {e}")
            continue
        if ohlcv.empty:
            continue

        try:
            inv = krx_fetcher.fetch_investor_flow(t.code, days=14)
        except Exception:
            import pandas as pd
            inv = pd.DataFrame()

        try:
            fo = krx_fetcher.fetch_foreign_ownership(t.code, days=30)
        except Exception:
            fo = None

        # 분석기 호출 (수집 가능한 것만; DART 의존 필터는 MVP 에서 skip)
        from src.analyzers import report_momentum
        from src.analyzers.base import GREEN, FilterResult, YELLOW

        filters = {
            "financial_trend": FilterResult(grade=YELLOW, score=60, details={"reason": "DART_skipped"}),
            "quant_health": FilterResult(grade=YELLOW, score=60, details={"reason": "DART_skipped"}),
            "margin_diagnosis": FilterResult(grade=YELLOW, score=60, details={"reason": "DART_skipped"}),
            "moat": FilterResult(
                grade=GREEN if t.code in _whitelist_codes() else YELLOW,
                score=80 if t.code in _whitelist_codes() else 50,
                details={"in_whitelist": t.code in _whitelist_codes()},
            ),
            "flow": flow_analysis.analyze(inv, fo) if not inv.empty else FilterResult(YELLOW, 50, {"reason": "no_flow"}),
            "credit_short": credit_short.analyze(t.code, short_top_codes),
            "nps": FilterResult(grade=YELLOW, score=60, details={"reason": "DART_skipped"}),
            "technical": technical.analyze(ohlcv),
            "report": report_momentum.analyze(t.code, tg_msgs),
        }

        ma = technical.moving_averages_daily(ohlcv)
        sig = buy_signal_generator.generate(t.code, t.name, filters, ma)
        signals.append(sig)

    # 3. payload 구성 + 서명
    buy_payload = {"date": today_str, "signals": signals}
    _write_signed(OUT_DIR / f"buy_signals_{today_str}.json", buy_payload, key)

    # macro
    idx = _kis_indices_safe()
    macro_payload = macro_brief.generate(
        kospi_change=_index_change(idx, "KOSPI"),
        kosdaq_change=_index_change(idx, "KOSDAQ"),
        usd_krw=0.0,
        foreign_kospi_net=0.0,
        claude_opinion_short="자동 생성 (지표 일부 미수집)",
    )
    _write_signed(OUT_DIR / f"macro_status_{today_str}.json", macro_payload, key)

    # blacklist (현 단계: SHORT_TOP10 만)
    blacklist = []
    for items in short_top.values():
        for it in items:
            blacklist.append(
                {
                    "code": it["code"],
                    "name": it["name"],
                    "blocked_until": today_str,
                    "block_reasons": [
                        {
                            "type": "SHORT_TOP10",
                            "detected_at": today_str,
                            "severity": "URGENT",
                            "description": "공매도 거래대금 Top10 자동 제외",
                        }
                    ],
                }
            )
    _write_signed(
        OUT_DIR / "blacklist_active.json",
        {"updated_at_date": today_str, "blacklist": blacklist},
        key,
    )

    log.info(f"done: signals={len(signals)} blacklist={len(blacklist)}")
    return 0


def _whitelist_codes() -> set[str]:
    p = config.DATA_DIR / "moat_whitelist.json"
    if not p.exists():
        return set()
    return set(json.loads(p.read_text(encoding="utf-8")).get("codes", []))


if __name__ == "__main__":
    sys.exit(main())
