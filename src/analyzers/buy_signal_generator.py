"""
buy_signal_generator. 9중 필터 결과 → STRONG_BUY/BUY/HOLD/AVOID 판정.

INTEGRATION.md §3.1 schema 그대로 출력 (envelope 은 호출자가 씌움).

[PATCHED v2 — 2026-05-06]
- ANALYST_TARGET_UP positive_signal 에 source_url 추가
  → report_momentum.details["matched_messages"] 첫 항목의 channel/message_id 로
    https://t.me/{channel}/{message_id} 형식 영구 링크 생성.
  → 카톡 메시지 끝 "🔍 리포트 근거" 섹션에서 사용.
- matched_messages 가 없거나 형식이 다르면 source_url=""(빈 문자열) 로 안전 fallback.
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
    # 임계값 보정 (DART/텔레그램 등 일부 필터 미수집 상태에서도 신호 노출).
    # 데이터 quality 100% 회복 시 STRONG_BUY=85, BUY=70 으로 다시 올릴 것.
    if has_red and score < 70:
        return "AVOID"
    if score >= 80:
        return "STRONG_BUY"
    if score >= 65:
        return "BUY"
    if score >= 50:
        return "HOLD"
    return "AVOID"


def _telegram_url_from_report(rep: FilterResult) -> str:
    """report_momentum.details.matched_messages 의 첫 메시지에서 t.me 영구 링크 생성.
    - matched_messages 비어 있거나 channel/message_id 누락 시 빈 문자열.
    - matched (구버전 키) 도 fallback 으로 받아줌.
    """
    if rep is None or not isinstance(rep.details, dict):
        return ""
    matched = rep.details.get("matched_messages") or rep.details.get("matched") or []
    if not matched or not isinstance(matched, list):
        return ""
    first = matched[0]
    if not isinstance(first, dict):
        return ""
    channel = first.get("channel") or first.get("channel_username") or ""
    msg_id = first.get("message_id")
    if not channel or msg_id is None:
        return ""
    try:
        msg_id_int = int(msg_id)
    except (TypeError, ValueError):
        return ""
    return f"https://t.me/{channel}/{msg_id_int}"


def _collect_positive(filters: dict[str, FilterResult]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    nps = filters.get("nps")
    if nps and nps.details.get("category") in ("신규", "확대"):
        out.append({"type": "NPS_NEW" if nps.details["category"] == "신규" else "NPS_ADD", "score": 15})
    rep = filters.get("report")
    if rep and rep.grade == STAR:
        src_url = _telegram_url_from_report(rep)
        entry: dict[str, Any] = {"type": "ANALYST_TARGET_UP", "score": 10}
        # 빈 문자열이어도 키는 추가 — 다운스트림 (kakao_send) 가 source_url 존재 여부로 분기.
        entry["source_url"] = src_url
        if src_url:
            entry["source_label"] = "리포트 메시지"
        out.append(entry)
    flow = filters.get("flow")
    if flow and flow.details.get("co_buy_ratio", 0) >= 0.7:
        out.append({"type": "STRONG_FLOW", "score": 8})
    # 차트 패턴: 1년선 위 + 5일선 위 + 최근 조정 후 지지
    tech = filters.get("technical")
    if tech and isinstance(tech.details, dict):
        pb = tech.details.get("pullback_pattern") or {}
        if pb.get("matched"):
            entry: dict[str, Any] = {"type": "PULLBACK_AT_MA250_SUPPORT", "score": 12}
            if pb.get("ma250"):
                entry["ma250"] = pb["ma250"]
            if pb.get("ma5"):
                entry["ma5"] = pb["ma5"]
            if pb.get("recent_pullback_pct") is not None:
                entry["recent_pullback_pct"] = pb["recent_pullback_pct"]
            out.append(entry)
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
    nine_scores = {k: int(filters[k].score) for k in NINE_FILTER_KEYS if k in filters}
    nine_details = {k: dict(filters[k].details or {}) for k in NINE_FILTER_KEYS if k in filters}
    weights = {k: 1 for k in NINE_FILTER_KEYS}
    weights["report"] = 0.8  # report 비중 약간 낮춤
    score_num = sum(filters[k].score * weights[k] for k in nine) if nine else 0
    score_den = sum(weights[k] for k in nine) if nine else 1
    score = int(score_num / score_den) if score_den else 0

    has_red = any(filters[k].grade == RED for k in nine)
    blocked_reasons = _block_reasons(filters)
    blocked = bool(blocked_reasons)
    signal = "AVOID" if blocked else _signal(score, has_red)

    # valid_until: 영업일 valid_days 후 (휴장일 skip). 봇 측 휴장일 skip 정책 일치.
    from src.utils.kst_time import next_business_day
    cur = today_kst()
    for _ in range(valid_days):
        cur = next_business_day(cur)
    valid_until = cur.strftime("%Y-%m-%d")

    return {
        "code": code,
        "name": name,
        "signal": signal,
        "score": score,
        "nine_filter": nine,
        "nine_filter_scores": nine_scores,
        "nine_filter_details": nine_details,
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
