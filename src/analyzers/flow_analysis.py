"""필터 ⑤ 수급. 외인+기관 동반 매수 일수 + 외인 보유율 변화."""

from __future__ import annotations

import pandas as pd

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult


def analyze(investor_flow_df: pd.DataFrame, foreign_owner_df: pd.DataFrame | None = None) -> FilterResult:
    """
    investor_flow_df: pykrx get_market_trading_value_by_date (날짜 인덱스, 외국인/기관/개인 등 컬럼).
    foreign_owner_df: pykrx get_exhaustion_rates_of_foreign_investor (선택).
    """
    if investor_flow_df is None or len(investor_flow_df) < 3:
        return FilterResult(grade=YELLOW, score=50, details={"reason": "insufficient_data"})

    foreign_col = next((c for c in investor_flow_df.columns if "외국인" in c), None)
    inst_col = next(
        (c for c in investor_flow_df.columns if "기관" in c and "외" not in c),
        None,
    )
    if not foreign_col or not inst_col:
        return FilterResult(grade=YELLOW, score=50, details={"reason": "missing_columns"})

    co_buy_days = int(((investor_flow_df[foreign_col] > 0) & (investor_flow_df[inst_col] > 0)).sum())
    days = len(investor_flow_df)
    co_ratio = co_buy_days / days

    foreign_delta = None
    if foreign_owner_df is not None and len(foreign_owner_df) >= 2:
        col = next((c for c in foreign_owner_df.columns if "외국인" in c or "비중" in c), None)
        if col:
            foreign_delta = float(foreign_owner_df[col].iloc[-1] - foreign_owner_df[col].iloc[0])

    if co_ratio >= 0.5 and (foreign_delta is None or foreign_delta >= 0):
        grade, score = GREEN, 85
    elif co_ratio >= 0.3:
        grade, score = YELLOW, 60
    else:
        grade, score = RED, 30

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "co_buy_days": co_buy_days,
            "co_buy_ratio": round(co_ratio, 2),
            "foreign_delta_pp": round(foreign_delta, 3) if foreign_delta is not None else None,
        },
    )
