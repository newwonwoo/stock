"""필터 ① 재무 추세. 분기 매출/영익 4분기 추이."""

from __future__ import annotations

from typing import Any

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult


def _qoq(values: list[float]) -> list[float]:
    return [(b - a) / abs(a) for a, b in zip(values, values[1:]) if a]


def analyze(quarterly_revenue: list[float], quarterly_op_profit: list[float]) -> FilterResult:
    """
    quarterly_revenue / op_profit: 오래된 분기부터 [Q-3, Q-2, Q-1, Q] 4개 (단위 무관, 일관성만 유지).
    """
    if len(quarterly_revenue) < 3 or len(quarterly_op_profit) < 3:
        return FilterResult(grade=YELLOW, score=50, details={"reason": "insufficient_data"})

    rev_chg = _qoq(quarterly_revenue)
    op_chg = _qoq(quarterly_op_profit)

    rev_up = sum(1 for x in rev_chg if x > 0)
    op_up = sum(1 for x in op_chg if x > 0)

    last_op = quarterly_op_profit[-1]
    op_loss_streak = 0
    for v in reversed(quarterly_op_profit):
        if v <= 0:
            op_loss_streak += 1
        else:
            break

    if op_loss_streak >= 2 or last_op <= 0:
        grade, score = RED, 25
    elif rev_up >= 2 and op_up >= 2:
        grade, score = GREEN, 85
    elif rev_up >= 1 and op_up >= 1:
        grade, score = YELLOW, 60
    else:
        grade, score = RED, 30

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "revenue_qoq": rev_chg,
            "op_qoq": op_chg,
            "op_loss_streak": op_loss_streak,
        },
    )
