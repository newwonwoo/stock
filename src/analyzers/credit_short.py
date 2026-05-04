"""필터 ⑥ 신용·공매도. 신용비율 + 공매도 Top10 매칭."""

from __future__ import annotations

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult


def analyze(
    code: str,
    short_top10_codes: set[str],
    credit_ratio: float | None = None,
) -> FilterResult:
    """
    short_top10_codes: KOSPI+KOSDAQ 공매도 거래대금 Top10 종목코드 합집합.
    credit_ratio: 신용잔고 / 시가총액 비율 (옵션, 0.05 = 5%).
    """
    if code in short_top10_codes:
        return FilterResult(
            grade=RED,
            score=10,
            details={"in_short_top10": True, "auto_excluded": True},
        )

    if credit_ratio is not None:
        if credit_ratio >= 0.05:
            grade, score = RED, 25
        elif credit_ratio >= 0.03:
            grade, score = YELLOW, 55
        else:
            grade, score = GREEN, 85
    else:
        grade, score = GREEN, 70  # 데이터 없으면 보수적 통과

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "in_short_top10": False,
            "credit_ratio": round(credit_ratio, 4) if credit_ratio is not None else None,
        },
    )
