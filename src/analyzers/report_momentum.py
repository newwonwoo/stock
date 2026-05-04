"""필터 ⑨ 리포트 모멘텀. 4주 내 코어 애널 매수 의견 카운트."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.analyzers.base import GREEN, RED, STAR, YELLOW, FilterResult


def analyze(code: str, telegram_messages: list[dict[str, Any]], window_days: int = 28) -> FilterResult:
    """
    telegram_messages: telegram_listener 결과 (CollectedMessage as dict).
    parsed.code 가 매칭되는 메시지만 대상. positive 카운트 기준.
    """
    cutoff = datetime.now().astimezone() - timedelta(days=window_days)
    pos = 0
    neg = 0
    target_ups = 0
    matched: list[dict[str, Any]] = []

    for m in telegram_messages:
        parsed = m.get("parsed", {})
        if parsed.get("code") != code:
            continue
        d_iso = m.get("date_iso", "")
        try:
            dt = datetime.fromisoformat(d_iso) if d_iso else None
        except Exception:
            dt = None
        if dt and dt < cutoff:
            continue
        sentiment = parsed.get("sentiment")
        if sentiment == "positive":
            pos += 1
            matched.append(m)
            if any("상향" in k for k in parsed.get("keywords", [])):
                target_ups += 1
        elif sentiment == "negative":
            neg += 1

    if neg > pos:
        grade, score = RED, 25
    elif pos >= 3 and target_ups >= 1:
        grade, score = STAR, 95
    elif pos >= 2:
        grade, score = GREEN, 80
    elif pos >= 1:
        grade, score = YELLOW, 60
    else:
        grade, score = YELLOW, 50

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "positive_count": pos,
            "negative_count": neg,
            "target_up_count": target_ups,
            "window_days": window_days,
        },
    )
