"""
4주 전 추천 종목 성과 추적.

흐름:
  1. data/recommendations/{4주 전}.json 로드
  2. 각 종목 현재가 (KRX 최근 영업일 종가) fetch
  3. (curr - entry) / entry 수익률 계산
  4. out/weekly_performance_{today}.json 박제

찾는 날짜: today - 28일 (가장 가까운 일요일 추천)
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from src import config
from src.utils.kst_time import fmt_date, now_kst, today_kst
from src.utils.logger import get_logger

log = get_logger("forward")

OUT_DIR = config.ROOT_DIR / "out"
RECS_DIR = config.DATA_DIR / "recommendations"


def _find_recommendation_file(target_date_iso: str) -> Path | None:
    """target_date_iso 와 가장 가까운 (±3일) 추천 파일."""
    if not RECS_DIR.exists():
        return None
    candidates = sorted(RECS_DIR.glob("*.json"))
    if not candidates:
        return None
    # 정확 일치 우선
    direct = RECS_DIR / f"{target_date_iso}.json"
    if direct.exists():
        return direct
    # ±3일 fallback
    from datetime import date, timedelta as td
    target = date.fromisoformat(target_date_iso)
    for delta in (1, -1, 2, -2, 3, -3):
        d = target + td(days=delta)
        p = RECS_DIR / f"{fmt_date(d)}.json"
        if p.exists():
            return p
    return None


def _current_close(code: str) -> int | None:
    try:
        from src.collectors.krx_fetcher import fetch_ohlcv
        df = fetch_ohlcv(code, days=5)
        if df is None or df.empty:
            return None
        return int(df["종가"].iloc[-1])
    except Exception as e:
        log.info(f"{code} 현재가 조회 실패: {e}")
        return None


def main() -> int:
    today = today_kst()
    target_iso = fmt_date(today - timedelta(days=28))

    rec_file = _find_recommendation_file(target_iso)
    if rec_file is None:
        log.info(f"4주 전 추천 파일 없음 (target≈{target_iso}) — 추적 skip")
        return 0

    rec = json.loads(rec_file.read_text(encoding="utf-8"))
    picks: list[dict[str, Any]] = rec.get("picks", [])

    rows = []
    for p in picks:
        code = p["code"]
        entry = p.get("entry_close")
        curr = _current_close(code)
        if entry and curr:
            ret_pct = round((curr - entry) / entry * 100, 2)
        else:
            ret_pct = None
        rows.append(
            {
                "code": code,
                "name": p.get("name"),
                "signal": p.get("signal"),
                "score": p.get("score"),
                "entry_date": p.get("entry_date"),
                "entry_close": entry,
                "current_close": curr,
                "return_pct": ret_pct,
                "reason_short": p.get("reason_short"),
            }
        )

    # 통계 (None 제외)
    valid = [r for r in rows if r["return_pct"] is not None]
    avg = round(sum(r["return_pct"] for r in valid) / len(valid), 2) if valid else None
    win = sum(1 for r in valid if r["return_pct"] > 0)
    win_rate = round(win / len(valid) * 100, 1) if valid else None

    payload = {
        "review_date": fmt_date(today),
        "recommended_on": rec.get("date"),
        "rec_file": rec_file.name,
        "picks_count": len(rows),
        "valid_count": len(valid),
        "avg_return_pct": avg,
        "win_rate_pct": win_rate,
        "rows": rows,
        "created_at": now_kst().replace(microsecond=0).isoformat(),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / f"weekly_performance_{fmt_date(today)}.json").open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log.info(f"performance: avg={avg}% win_rate={win_rate}% (n={len(valid)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
