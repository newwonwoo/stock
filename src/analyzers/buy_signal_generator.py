"""
buy_signal_generator. 9중 필터 결과 → STRONG_BUY/BUY/HOLD/AVOID 판정.

INTEGRATION.md §3.1 schema 그대로 출력 (envelope 은 호출자가 씌움).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from src.analyzers.base import RED, STAR, FilterResult
from src.utils.kst_time import fmt_date, now_kst, today_kst

NINE_FILTER_KEYS = (
    "financial_trend",
    "quant_health",
    "margin_diagnosis",
    "moat",
    "flow",
    "credit_short",
    "nps",
    "technical",
    "report",
)


def _signal(score: int, has_red: bool) -> str:
    if has_red and score < 75:
        return "AVOID"
    if score >= 90:
        return "STRONG_BUY"
    if score >= 70:
        return "BUY"
    if score >= 50:
        return "HOLD"
    return "AVOID"


def _collect_positive(filters: dict[str, FilterResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    nps = filters.get("nps")
    if nps and nps.details.get("category") in ("신규", "확대"):
        out.append({"type": "NPS_NEW" if nps.details["category"] == "신규" else "NPS_ADD", "score": 15})
    rep = filters.get("report")
    if rep and rep.grade == STAR:
        out.append({"type": "ANALYST_TARGET_UP", "score": 10})
    flow = filters.get("flow")
    if flow and flow.details.get("co_buy_ratio", 0) >= 0.7:
        out.append({"type": "STRONG_FLOW", "score": 8})
    return out


def _collect_negative(filters: dict[str, FilterResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    nps = filters.get("nps")
    if nps and nps.details.get("category") in ("축소대폭", "전량매도"):
        out.append({"type": "NPS_REDUCE", "score": -10})
    cs = filters.get("credit_short")
    if cs and cs.details.get("in_short_top10"):
        out.append({"type": "SHORT_TOP10", "score": -20})
    return out


def _block_reasons(filters: dict[str, FilterResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cs = filters.get("credit_short")
    if cs and cs.details.get("in_short_top10"):
        out.append(
            {
                "type": "SHORT_TOP10",
                "detected_at": fmt_date(today_kst()),
                "severity": "URGENT",
                "description": "공매도 거래대금 Top10 종목 자동 제외",
            }
        )
    return out


def generate(
    code: str,
    name: str,
    filters: dict[str, FilterResult],
    moving_averages: dict[str, int | None],
    *,
    valid_days: int = 5,
) -> dict[str, Any]:
    nine = {k: filters[k].grade for k in NINE_FILTER_KEYS if k in filters}
    weights = {k: 1 for k in NINE_FILTER_KEYS}
    weights["report"] = 0.8  # report 비중 약간 낮춤
    score_num = sum(filters[k].score * weights[k] for k in nine) if nine else 0
    score_den = sum(weights[k] for k in nine) if nine else 1
    score = int(score_num / score_den) if score_den else 0

    has_red = any(filters[k].grade == RED for k in nine)
    blocked_reasons = _block_reasons(filters)
    blocked = bool(blocked_reasons)
    signal = "AVOID" if blocked else _signal(score, has_red)

    valid_until = (today_kst() + timedelta(days=valid_days)).strftime("%Y-%m-%d")

    return {
        "code": code,
        "name": name,
        "signal": signal,
        "score": score,
        "nine_filter": nine,
        "positive_signals": _collect_positive(filters),
        "negative_signals": _collect_negative(filters),
        "blocked": blocked,
        "block_reasons": blocked_reasons,
        "moving_averages": {
            "ma10": moving_averages.get("ma10"),
            "ma15": moving_averages.get("ma15"),
        },
        "valid_until": valid_until,
        "created_at": now_kst().replace(microsecond=0).isoformat(),
    }
