"""필터 ⑧ 기술적. 일봉→주봉, 60주선, 주봉 RSI(14), 양봉 반전."""

from __future__ import annotations

import pandas as pd

from src.analyzers.base import GREEN, RED, YELLOW, FilterResult

OPEN_COL = "시가"
HIGH_COL = "고가"
LOW_COL = "저가"
CLOSE_COL = "종가"
VOL_COL = "거래량"


def daily_to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """pykrx 일봉 (날짜 인덱스) → 주봉 (월요일 시초, 금요일 종가)."""
    if daily.empty:
        return daily
    d = daily.copy()
    d.index = pd.to_datetime(d.index)
    rule = "W-FRI"
    weekly = pd.DataFrame(
        {
            OPEN_COL: d[OPEN_COL].resample(rule).first(),
            HIGH_COL: d[HIGH_COL].resample(rule).max(),
            LOW_COL: d[LOW_COL].resample(rule).min(),
            CLOSE_COL: d[CLOSE_COL].resample(rule).last(),
            VOL_COL: d[VOL_COL].resample(rule).sum(),
        }
    ).dropna()
    return weekly


def _rsi(close: pd.Series, period: int = 14) -> float:
    if len(close) < period + 1:
        return 50.0
    delta = close.diff().dropna()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def analyze(daily_ohlcv: pd.DataFrame) -> FilterResult:
    if daily_ohlcv is None or len(daily_ohlcv) < 60:
        return FilterResult(grade=YELLOW, score=50, details={"reason": "insufficient_data"})

    weekly = daily_to_weekly(daily_ohlcv)
    if len(weekly) < 60:
        return FilterResult(grade=YELLOW, score=50, details={"reason": "insufficient_weekly"})

    last = weekly.iloc[-1]
    ma60w = weekly[CLOSE_COL].rolling(60).mean().iloc[-1]
    rsi14 = _rsi(weekly[CLOSE_COL])

    above_ma60w = last[CLOSE_COL] > ma60w
    bullish_engulf = (
        last[CLOSE_COL] > last[OPEN_COL]
        and len(weekly) >= 2
        and weekly.iloc[-2][CLOSE_COL] < weekly.iloc[-2][OPEN_COL]
        and last[CLOSE_COL] > weekly.iloc[-2][OPEN_COL]
    )

    if above_ma60w and 30 <= rsi14 <= 70 and bullish_engulf:
        grade, score = GREEN, 90
    elif above_ma60w and 30 <= rsi14 <= 75:
        grade, score = GREEN, 75
    elif above_ma60w:
        grade, score = YELLOW, 60
    else:
        grade, score = RED, 30

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "above_ma60w": above_ma60w,
            "rsi14_weekly": round(rsi14, 1),
            "bullish_engulf": bullish_engulf,
            "last_close": float(last[CLOSE_COL]),
            "ma60w": float(ma60w),
        },
    )


def moving_averages_daily(daily_ohlcv: pd.DataFrame) -> dict[str, int | None]:
    """일봉 MA10 / MA15 (분할 진입 트리거 가격)."""
    if daily_ohlcv is None or len(daily_ohlcv) < 15:
        return {"ma10": None, "ma15": None}
    ma10 = daily_ohlcv[CLOSE_COL].rolling(10).mean().iloc[-1]
    ma15 = daily_ohlcv[CLOSE_COL].rolling(15).mean().iloc[-1]
    return {"ma10": int(ma10), "ma15": int(ma15)}
