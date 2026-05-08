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

    # 추가: "추세 위 + 조정 후 지지" 차트 패턴 (1년선 위 + 5일선 위 + 최근 조정).
    pullback = detect_pullback_at_ma250_support(daily_ohlcv)

    if above_ma60w and 30 <= rsi14 <= 70 and bullish_engulf:
        grade, score = GREEN, 90
    elif above_ma60w and 30 <= rsi14 <= 75:
        grade, score = GREEN, 75
    elif above_ma60w:
        grade, score = YELLOW, 60
    else:
        grade, score = RED, 30

    # 패턴 매칭 시 boost (단, RED 면 boost X)
    if pullback["matched"] and grade != RED:
        score = min(95, score + 8)
        if grade == YELLOW:
            grade = GREEN

    return FilterResult(
        grade=grade,
        score=score,
        details={
            "above_ma60w": above_ma60w,
            "rsi14_weekly": round(rsi14, 1),
            "bullish_engulf": bullish_engulf,
            "last_close": float(last[CLOSE_COL]),
            "ma60w": float(ma60w),
            "pullback_pattern": pullback,
        },
    )


def moving_averages_daily(daily_ohlcv: pd.DataFrame) -> dict[str, int | None]:
    """일봉 MA10 / MA15 (분할 진입 트리거 가격)."""
    if daily_ohlcv is None or len(daily_ohlcv) < 15:
        return {"ma10": None, "ma15": None}
    ma10 = daily_ohlcv[CLOSE_COL].rolling(10).mean().iloc[-1]
    ma15 = daily_ohlcv[CLOSE_COL].rolling(15).mean().iloc[-1]
    return {"ma10": int(ma10), "ma15": int(ma15)}


def detect_pullback_at_ma250_support(
    daily_ohlcv: pd.DataFrame,
    pullback_lookback_days: int = 60,
    pullback_threshold_pct: float = 15.0,
) -> dict:
    """
    "추세 위 + 조정 후 지지" 패턴 감지.

    조건:
      1. 현재가 > MA250 (1년선 위 = 장기 상승 추세)
      2. 현재가 > MA5 (단기 반등/지지)
      3. 최근 pullback_lookback_days 일 (default 60일 ~ 3개월) 내에 가격이
         MA250 까지 가까워진 흔적이 있음 — 종가-MA250 의 거리 (%) 가
         0 ~ pullback_threshold_pct (default 15%) 사이로 눌렸음.
         즉 "추세 라인까지 한 번 눌렸다가 다시 올라온" 패턴.

    셋 다 True 면 매수 후보 패턴.

    반환:
      {
        "matched": bool,
        "above_ma250": bool,
        "above_ma5": bool,
        "recent_pullback_pct": float | None  (최근 lookback 의 MA250 까지 최저 거리 %),
        "ma5": int | None,
        "ma250": int | None,
        "current": int,
      }
    """
    out = {
        "matched": False,
        "above_ma250": False,
        "above_ma5": False,
        "recent_pullback_pct": None,
        "ma5": None,
        "ma250": None,
        "current": None,
    }
    if daily_ohlcv is None or len(daily_ohlcv) < 250:
        return out

    closes = daily_ohlcv[CLOSE_COL]
    ma5 = closes.rolling(5).mean()
    ma250 = closes.rolling(250).mean()

    cur = float(closes.iloc[-1])
    cur_ma5 = float(ma5.iloc[-1])
    cur_ma250 = float(ma250.iloc[-1])

    out["current"] = int(cur)
    out["ma5"] = int(cur_ma5)
    out["ma250"] = int(cur_ma250)
    out["above_ma5"] = cur > cur_ma5
    out["above_ma250"] = cur > cur_ma250

    # 최근 N일 내 MA250 까지 거리 최소값 (= 가장 가까이 눌렸을 때)
    recent_closes = closes.iloc[-pullback_lookback_days:]
    recent_ma250 = ma250.iloc[-pullback_lookback_days:]
    if len(recent_closes) and len(recent_ma250):
        # (close - ma250) / ma250 의 최소 거리 (%). 음수면 ma250 깼다는 뜻.
        rel = ((recent_closes - recent_ma250) / recent_ma250 * 100).dropna()
        if len(rel):
            min_rel = float(rel.min())
            out["recent_pullback_pct"] = round(min_rel, 2)
            recent_pulled_in = 0 <= min_rel <= pullback_threshold_pct
        else:
            recent_pulled_in = False
    else:
        recent_pulled_in = False

    out["matched"] = (
        out["above_ma250"]
        and out["above_ma5"]
        and recent_pulled_in
    )
    return out
