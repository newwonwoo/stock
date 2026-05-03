"""필터 ② 정량 건전성. DSO / OCF·영익 / 부채비율 / 수주잔고."""

from __future__ import annotations

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult


def analyze(
    revenue: float,
    receivables: float,
    op_profit: float,
    operating_cf: float,
    total_debt: float,
    equity: float,
    backlog: float | None = None,
) -> FilterResult:
    """
    revenue / receivables / op_profit / operating_cf / total_debt / equity: 최근 분기 누적치.
    backlog: 수주잔고 (None 이면 평가 제외).
    """
    if revenue <= 0 or equity <= 0:
        return FilterResult(grade=YELLOW, score=50, details={"reason": "insufficient_data"})

    dso = (receivables / revenue) * 90  # 분기 기준 days
    ocf_to_op = (operating_cf / op_profit) if op_profit > 0 else 0
    debt_ratio = total_debt / equity
    backlog_ratio = (backlog / revenue) if (backlog and revenue) else None

    flags = {
        "dso_ok": dso < 90,
        "ocf_ok": ocf_to_op >= 0.7,
        "debt_ok": debt_ratio < 1.5,
        "backlog_ok": backlog_ratio is None or backlog_ratio >= 0.5,
    }
    ok_count = sum(1 for v in flags.values() if v)

    if ok_count == 4:
        grade, score = GREEN, 90
    elif ok_count == 3:
        grade, score = GREEN, 75
    elif ok_count == 2:
        grade, score = YELLOW, 55
    else:
        grade, score = RED, 30

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "dso": round(dso, 1),
            "ocf_to_op": round(ocf_to_op, 2),
            "debt_ratio": round(debt_ratio, 2),
            "backlog_ratio": round(backlog_ratio, 2) if backlog_ratio else None,
            **flags,
        },
    )
