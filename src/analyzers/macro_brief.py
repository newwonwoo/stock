"""macro_status payload 생성. INTEGRATION.md §3.4 schema."""

from __future__ import annotations

from typing import Any

from src.utils.kst_time import fmt_date, now_kst, today_kst


def _classify_overall(kospi_chg: float, foreign_net: float, usdkrw: float) -> str:
    risk = 0
    if kospi_chg <= -1.5:
        risk += 1
    if foreign_net <= -300_000_000_000:  # 3천억 순매도
        risk += 1
    if usdkrw >= 1400:
        risk += 1
    if risk >= 3:
        return "🚨"
    if risk >= 2:
        return "🔴"
    if risk >= 1:
        return "🟡"
    return "🟢"


def generate(
    *,
    kospi_change: float = 0.0,
    kosdaq_change: float = 0.0,
    sp500_change: float = 0.0,
    usd_krw: float = 0.0,
    us_10y_yield: float = 0.0,
    foreign_kospi_net: float = 0.0,
    institution_kospi_net: float = 0.0,
    total_kospi_value: float = 0.0,
    events_today: list[dict[str, Any]] | None = None,
    claude_opinion_short: str = "",
) -> dict[str, Any]:
    overall = _classify_overall(kospi_change, foreign_kospi_net, usd_krw)
    return {
        "date": fmt_date(today_kst()),
        "overall": overall,
        "indicators": {
            "kospi_change": kospi_change,
            "kosdaq_change": kosdaq_change,
            "sp500_change": sp500_change,
            "usd_krw": usd_krw,
            "us_10y_yield": us_10y_yield,
            "foreign_kospi_net": foreign_kospi_net,
            "institution_kospi_net": institution_kospi_net,
            "total_kospi_value": total_kospi_value,
        },
        "events_today": events_today or [],
        "claude_opinion_short": claude_opinion_short,
        "created_at": now_kst().replace(microsecond=0).isoformat(),
    }
