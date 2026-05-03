"""
CB·BW 행사기간 추적기.

흐름:
  1. CB_BW_ISSUE 공시 감지 시 → tracker 에 entry 등록
       - rcept_no, code, issued_date
       - exercise_start_date: 발행일 + 365일 (한국 자본시장법 1년 규제 default)
       - 실제 행사기간이 더 짧으면 추후 details 파싱으로 보정 (TODO)
  2. 매일 daily.yml 에서 호출 → 보유 종목 중 행사기간 D-N 도달 종목 선별
       - D-30: REVIEW
       - D-7:  REVIEW (가중)
       - D-0:  URGENT (행사 시작일)
       - 행사 후 60일: MONITOR (CB_BW_NEAR_EXERCISE)
  3. 행사 만료 (D+730 = 발행 후 2년) 후 entry 삭제

state file: .cache/cb_tracker.json
  {"<stock_code>": [
     {"rcept_no": "...", "issued_date": "YYYY-MM-DD",
      "exercise_start_date": "YYYY-MM-DD",
      "expires_at": "YYYY-MM-DD",
      "raw_report_nm": "..."}
  ]}
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src import config
from src.utils.kst_time import fmt_date, today_kst
from src.utils.logger import get_logger

log = get_logger("cb_bw")

CB_TRACKER_FILE = config.CACHE_DIR / "cb_tracker.json"
DEFAULT_EXERCISE_DELAY_DAYS = 365
ENTRY_LIFETIME_DAYS = 730   # 발행 후 2년 보관
ALERT_THRESHOLDS = (30, 7, 0)


@dataclass
class CbAlert:
    code: str
    rcept_no: str
    days_until_exercise: int
    severity: str               # URGENT / REVIEW / MONITOR
    exercise_start_date: str
    issued_date: str
    raw_report_nm: str


def _load() -> dict[str, list[dict[str, Any]]]:
    if not CB_TRACKER_FILE.exists():
        return {}
    try:
        return json.loads(CB_TRACKER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(state: dict[str, list[dict[str, Any]]]) -> None:
    CB_TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    CB_TRACKER_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def register_cb(
    code: str,
    rcept_no: str,
    raw_report_nm: str,
    issued_date: date | None = None,
    exercise_start_date: date | None = None,
) -> bool:
    """신규 CB 등록. 같은 rcept_no 이미 있으면 False, 신규 등록이면 True."""
    state = _load()
    issued = issued_date or today_kst()
    exercise = exercise_start_date or (issued + timedelta(days=DEFAULT_EXERCISE_DELAY_DAYS))
    expires = issued + timedelta(days=ENTRY_LIFETIME_DAYS)

    entries = state.setdefault(code, [])
    if any(e.get("rcept_no") == rcept_no for e in entries):
        return False
    entries.append(
        {
            "rcept_no": rcept_no,
            "issued_date": fmt_date(issued),
            "exercise_start_date": fmt_date(exercise),
            "expires_at": fmt_date(expires),
            "raw_report_nm": raw_report_nm,
        }
    )
    _save(state)
    log.info(f"CB tracker: {code} rcept={rcept_no} exercise={fmt_date(exercise)}")
    return True


def cleanup_expired(today: date | None = None) -> int:
    """만료된 entry 삭제. 삭제된 개수 반환."""
    today = today or today_kst()
    state = _load()
    removed = 0
    for code in list(state.keys()):
        kept = []
        for e in state[code]:
            try:
                exp = date.fromisoformat(e.get("expires_at", ""))
            except Exception:
                exp = today + timedelta(days=1)
            if exp >= today:
                kept.append(e)
            else:
                removed += 1
        if kept:
            state[code] = kept
        else:
            del state[code]
    if removed:
        _save(state)
        log.info(f"CB tracker cleanup: removed {removed} expired entries")
    return removed


def _severity_for(days_until: int) -> str | None:
    if days_until == 0 or days_until < 0:
        return "URGENT"
    if days_until <= 7:
        return "REVIEW"
    if days_until <= 30:
        return "REVIEW"
    return None


def find_alerts(
    today: date | None = None,
    only_codes: set[str] | None = None,
) -> list[CbAlert]:
    """
    오늘 alert 발생 entry 들. only_codes 지정 시 그 종목만.
    DETAIL: D-30/D-7/D-0 *정확히 일치* 만 emit (중복 방지).
    """
    today = today or today_kst()
    state = _load()
    out: list[CbAlert] = []
    for code, entries in state.items():
        if only_codes is not None and code not in only_codes:
            continue
        for e in entries:
            try:
                ex_date = date.fromisoformat(e["exercise_start_date"])
            except Exception:
                continue
            days_until = (ex_date - today).days
            if days_until not in ALERT_THRESHOLDS:
                continue
            sev = _severity_for(days_until)
            if not sev:
                continue
            out.append(
                CbAlert(
                    code=code,
                    rcept_no=e.get("rcept_no", ""),
                    days_until_exercise=days_until,
                    severity=sev,
                    exercise_start_date=e["exercise_start_date"],
                    issued_date=e.get("issued_date", ""),
                    raw_report_nm=e.get("raw_report_nm", ""),
                )
            )
    return out
