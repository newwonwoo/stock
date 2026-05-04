"""
백테스트 성과 지표. Sharpe / MDD / 승률 / 알파(KOSPI 대비).

주의:
  - Sharpe: 무위험 수익률 0 가정 (단순화). 연환산 252영업일.
  - MDD: equity curve 의 peak 대비 최대 낙폭.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Sequence


@dataclass
class Metrics:
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    mdd_pct: float
    win_rate_pct: float
    avg_trade_pct: float
    trade_count: int
    alpha_vs_benchmark_pct: float | None = None


def _daily_returns(equity_curve: Sequence[tuple[date, float]]) -> list[float]:
    rets: list[float] = []
    for prev, cur in zip(equity_curve, equity_curve[1:]):
        if prev[1]:
            rets.append((cur[1] - prev[1]) / prev[1])
    return rets


def _max_drawdown(equity_curve: Sequence[tuple[date, float]]) -> float:
    peak = -float("inf")
    mdd = 0.0
    for _, v in equity_curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (v - peak) / peak
            if dd < mdd:
                mdd = dd
    return mdd  # 음수


def _cagr(equity_curve: Sequence[tuple[date, float]], initial: float) -> float:
    if not equity_curve or initial <= 0:
        return 0.0
    final = equity_curve[-1][1]
    days = (equity_curve[-1][0] - equity_curve[0][0]).days
    if days <= 0 or final <= 0:
        return 0.0
    years = days / 365.25
    return (final / initial) ** (1 / years) - 1


def compute(
    equity_curve: Sequence[tuple[date, float]],
    initial: float,
    trade_returns_pct: Sequence[float],
    benchmark_total_return_pct: float | None = None,
) -> Metrics:
    rets = _daily_returns(equity_curve)
    sharpe = 0.0
    if len(rets) > 1:
        std = statistics.pstdev(rets)
        if std > 0:
            sharpe = round((statistics.fmean(rets) / std) * math.sqrt(252), 2)

    mdd = _max_drawdown(equity_curve)
    cagr = _cagr(equity_curve, initial)

    final = equity_curve[-1][1] if equity_curve else initial
    total_ret = (final - initial) / initial if initial else 0.0

    wins = sum(1 for r in trade_returns_pct if r > 0)
    win_rate = (wins / len(trade_returns_pct) * 100) if trade_returns_pct else 0.0
    avg_trade = (statistics.fmean(trade_returns_pct)) if trade_returns_pct else 0.0

    alpha = None
    if benchmark_total_return_pct is not None:
        alpha = round(total_ret * 100 - benchmark_total_return_pct, 2)

    return Metrics(
        total_return_pct=round(total_ret * 100, 2),
        cagr_pct=round(cagr * 100, 2),
        sharpe=sharpe,
        mdd_pct=round(mdd * 100, 2),
        win_rate_pct=round(win_rate, 1),
        avg_trade_pct=round(avg_trade, 2),
        trade_count=len(trade_returns_pct),
        alpha_vs_benchmark_pct=alpha,
    )
