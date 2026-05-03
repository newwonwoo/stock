"""
sell_signal_generator. 분류된 공시 → INTEGRATION.md §3.2 sell_signal payload.

봇이 보유 중일 때만 의미. 리서치는 모든 공시 대상으로 발행 → 봇이 자체 필터링.
signal_id 는 (date, code, rcept_no) 결정적 → 중복 푸시 방지.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from src.analyzers.disclosure_classifier import ClassifiedDisclosure
from src.utils.kst_time import fmt_compact, now_kst, today_kst


SELL_TRIGGERING_EFFECTS = ("SELL_TRIGGER",)


def make_signal_id(date_str: str, code: str, rcept_no: str | None = None) -> str:
    """결정적 signal_id. 같은 공시는 항상 같은 id → 중복 가드."""
    suffix = (rcept_no or "X")[-6:]
    return f"{date_str.replace('-', '')}_{code}_{suffix}"


def _action_recommendation(severity: str, type_code: str) -> str:
    if severity == "URGENT":
        return "전량 시초가 매도"
    if severity == "REVIEW":
        return "분할 매도 검토"
    return "관찰만"


def _short_reason(cd: ClassifiedDisclosure) -> str:
    return cd.description or cd.type_code


def generate(
    *,
    code: str,
    name: str,
    classified: ClassifiedDisclosure,
    rcept_no: str | None = None,
    rcept_dt: str | None = None,
    expire_days: int = 1,
) -> dict[str, Any] | None:
    """SELL_TRIGGER 효과만 sell_signal 생성. POSITIVE/NEUTRAL/BLOCK_BUY 는 None 반환."""
    if classified.effect not in SELL_TRIGGERING_EFFECTS:
        return None

    today_str = (rcept_dt and rcept_dt[:8]) or fmt_compact(today_kst())
    today_iso = f"{today_str[:4]}-{today_str[4:6]}-{today_str[6:8]}"

    expires_at = (now_kst() + timedelta(days=expire_days)).replace(microsecond=0).isoformat()

    return {
        "signal_id": make_signal_id(today_iso, code, rcept_no),
        "code": code,
        "name": name,
        "severity": classified.severity,
        "trigger": {
            "type": "DISCLOSURE",
            "subtype": classified.type_code,
            "details": classified.raw_report_nm,
        },
        "action_recommendation": _action_recommendation(classified.severity, classified.type_code),
        "reason_short": _short_reason(classified),
        "created_at": now_kst().replace(microsecond=0).isoformat(),
        "expires_at": expires_at,
        "consumed": False,
    }
