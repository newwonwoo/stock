"""
일요일 주간 종목 추천 5개 선정.

흐름:
  1. 가장 최근 buy_signals_*.json 읽기 (out/ 또는 generate_signals 신규 호출)
  2. signal in {STRONG_BUY, BUY} + blocked=false 만 필터
  3. score 내림차순 → top 5
  4. 각 추천에 사유 (positive_signals 요약, nine_filter 등) 첨부
  5. data/recommendations/{YYYY-MM-DD}.json 박제 (forward_tracker 추적용)
  6. out/weekly_picks_{date}.json (Claude.ai 루틴이 카톡으로 가공)

KRX 종가를 entry_close 로 기록 (4주 후 추적 시 비교 기준).
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path
from typing import Any

from src import config
from src.utils.kst_time import fmt_date, now_kst, prev_business_day, today_kst
from src.utils.logger import get_logger

log = get_logger("weekly_picks")

OUT_DIR = config.ROOT_DIR / "out"
RECS_DIR = config.DATA_DIR / "recommendations"
TOP_N = 5


def _latest_buy_signals() -> dict[str, Any] | None:
    """가장 최근 buy_signals_*.json envelope 의 data 부분 반환."""
    files = sorted(glob.glob(str(OUT_DIR / "buy_signals_*.json")))
    if not files:
        return None
    p = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    return p.get("data") or p  # 봉투 없는 경우 fallback


def _entry_close(code: str) -> int | None:
    """가장 최근 영업일 종가."""
    try:
        from src.collectors.krx_fetcher import fetch_ohlcv
        df = fetch_ohlcv(code, days=5)
        if df is None or df.empty:
            return None
        return int(df["종가"].iloc[-1])
    except Exception as e:
        log.info(f"{code} 종가 조회 실패: {e}")
        return None


def _summarize_reason(sig: dict[str, Any]) -> str:
    nine = sig.get("nine_filter", {})
    pos = sig.get("positive_signals", [])
    parts = []
    if pos:
        parts.append(", ".join(p["type"] for p in pos[:3]))
    green_count = sum(1 for v in nine.values() if v == "🟢" or v == "⭐")
    parts.append(f"필터 {green_count}/9 통과")
    return " · ".join(parts)


def main() -> int:
    bs = _latest_buy_signals()
    if not bs:
        log.info("buy_signals 파일 없음 — 먼저 generate_signals 실행 필요")
        return 1

    candidates = [
        s for s in bs.get("signals", [])
        if s.get("signal") in ("STRONG_BUY", "BUY") and not s.get("blocked")
    ]
    candidates.sort(key=lambda s: s.get("score", 0), reverse=True)
    picks = candidates[:TOP_N]

    today = today_kst()
    today_str = fmt_date(today)
    entry_date = prev_business_day(today + __import__("datetime").timedelta(days=1))
    entry_str = fmt_date(entry_date)

    enriched: list[dict[str, Any]] = []
    for s in picks:
        entry = _entry_close(s["code"])
        enriched.append(
            {
                "code": s["code"],
                "name": s["name"],
                "signal": s["signal"],
                "score": s["score"],
                "nine_filter": s.get("nine_filter", {}),
                "moving_averages": s.get("moving_averages", {}),
                "reason_short": _summarize_reason(s),
                "entry_date": entry_str,
                "entry_close": entry,
            }
        )

    payload = {
        "date": today_str,
        "entry_reference_date": entry_str,
        "picks_count": len(enriched),
        "picks": enriched,
        "created_at": now_kst().replace(microsecond=0).isoformat(),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / f"weekly_picks_{today_str}.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log.info(f"weekly_picks: {len(enriched)} → out/weekly_picks_{today_str}.json")

    # 추적용 영구 박제 (auto-commit 으로 repo 에 들어감)
    RECS_DIR.mkdir(parents=True, exist_ok=True)
    with (RECS_DIR / f"{today_str}.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log.info(f"recommendations: data/recommendations/{today_str}.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())
