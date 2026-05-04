"""필터 ⑦ NPS (국민연금) 분기 변동. 신규/확대/축소/매도 분류."""

from __future__ import annotations

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult


def _classify(prev_pct: float | None, curr_pct: float | None) -> tuple[str, int]:
    if prev_pct is None and curr_pct is not None:
        return "신규", 90
    if prev_pct is not None and curr_pct is None:
        return "전량매도", 10
    if prev_pct is None or curr_pct is None:
        return "없음", 50
    delta = curr_pct - prev_pct
    if delta >= 0.5:
        return "확대", 85
    if delta >= 0:
        return "유지", 65
    if delta >= -0.5:
        return "축소소폭", 50
    return "축소대폭", 25


def analyze(prev_quarter_pct: float | None, curr_quarter_pct: float | None) -> FilterResult:
    """
    NPS 보유 비중 (%, 시가총액 대비). DART 대량보유 보고에서 추출.
    """
    category, score = _classify(prev_quarter_pct, curr_quarter_pct)

    if score >= 80:
        grade = GREEN
    elif score >= 50:
        grade = YELLOW
    else:
        grade = RED

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "category": category,
            "prev_pct": prev_quarter_pct,
            "curr_pct": curr_quarter_pct,
        },
    )
