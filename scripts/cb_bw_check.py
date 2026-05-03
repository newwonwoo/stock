"""
CB·BW 행사기간 D-N 도달 체크 + sell_signal 발행.

매일 daily.yml 에서 호출. 보유 종목 중 D-30/D-7/D-0 정확히 일치하는 entry 만 emit.
보유 종목이 fetch 안 되면 skip (매도 시그널 의미 없음).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from datetime import timedelta

from src import config
from src.analyzers.cb_bw_tracker import cleanup_expired, find_alerts
from src.integrations.bot_dashboard import held_stock_codes
from src.utils.kst_time import fmt_date, now_kst, today_kst
from src.utils.logger import get_logger

log = get_logger("cb_check")

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


def main() -> int:
    key = os.environ.get("RESEARCH_HMAC_KEY", "")
    if not key:
        log.info("RESEARCH_HMAC_KEY 미설정 — 종료")
        return 1

    cleanup_expired()

    held = held_stock_codes()
    if not held:
        log.info("보유 종목 0 또는 dashboard 사용 불가 — CB 알림 발행 skip")
        return 0

    alerts = find_alerts(only_codes=held)
    if not alerts:
        log.info("오늘 CB 알림 대상 없음")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    today = today_kst()
    expires_at = (now_kst() + timedelta(days=1)).replace(microsecond=0).isoformat()
    written = 0

    for a in alerts:
        signal_id = f"{fmt_date(today).replace('-', '')}_{a.code}_CB{a.days_until_exercise:+04d}"
        sig = {
            "signal_id": signal_id,
            "code": a.code,
            "name": "",
            "severity": a.severity,
            "trigger": {
                "type": "CB_EXERCISE",
                "subtype": f"D{a.days_until_exercise:+d}",
                "details": (
                    f"행사 시작 {a.exercise_start_date} (D{a.days_until_exercise:+d}). "
                    f"발행: {a.issued_date} / {a.raw_report_nm}"
                ),
            },
            "action_recommendation": (
                "전량 시초가 매도" if a.severity == "URGENT" else "분할 매도 검토"
            ),
            "reason_short": f"CB 행사기간 D{a.days_until_exercise:+d}",
            "created_at": now_kst().replace(microsecond=0).isoformat(),
            "expires_at": expires_at,
            "consumed": False,
        }
        path = OUT_DIR / f"sell_signal_{signal_id}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(_wrap(sig, key), f, ensure_ascii=False, indent=2)
            f.write("\n")
        log.info(f"CB alert emitted: {a.code} D{a.days_until_exercise:+d} ({a.severity})")
        written += 1

    log.info(f"done: alerts={written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
