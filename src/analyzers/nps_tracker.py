"""필터 ⑦ NPS (국민연금) 분기 변동. 신규/확대/축소/매도 분류 + 일자 박제."""

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


def analyze(
    prev_quarter_pct: float | None,
    curr_quarter_pct: float | None,
    *,
    latest_bsis_de: str | None = None,
    latest_rcept_dt: str | None = None,
    first_buy_de: str | None = None,
) -> FilterResult:
    """
    NPS 보유 비중 (%, 시가총액 대비). DART 대량보유 보고에서 추출.

    선택 인자 (kakao_send 가 메시지에 노출):
      latest_bsis_de  : 가장 최근 보고의 변동 기준일 (실제 매수/매도일)
      latest_rcept_dt : DART 공시 접수일
      first_buy_de    : NPS 가 처음 등장한 보고의 변동 기준일 (신규 편입 시작)
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
            "latest_bsis_de": latest_bsis_de,
            "latest_rcept_dt": latest_rcept_dt,
            "first_buy_de": first_buy_de,
        },
    )
