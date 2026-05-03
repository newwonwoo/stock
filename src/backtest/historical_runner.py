"""
5년 historical 백테스트 — KRX 기반 모멘텀 (3 필터 MVP).

설계:
  - LOOKBACK_YEARS=5 (env 로 조정 가능)
  - 매월 첫 영업일 rebalance
  - universe: 그 시점 시총 ≥5천억 KOSPI+KOSDAQ → top N
  - 종목별 점수 = 0.5 × technical + 0.3 × flow + 0.2 × credit_short
       technical: 60일 모멘텀 (현재가 / 60일 전가)
       flow: 외인+기관 동반 매수일 (최근 20영업일 중)
       credit_short: 공매도 Top10 매칭 시 0, 외 1.0
  - score 상위 MAX_HOLDINGS 매수, 1개월 보유 후 청산
  - 벤치마크: KOSPI 종합 지수 동기간 수익률

DART 의존 4 필터 (financial_trend / quant_health / margin_diagnosis / nps)
는 본 MVP 에서 제외. 다음 라운드에서 prefetch 캐시 후 추가.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from src.backtest.metrics import compute as compute_metrics
from src.backtest.portfolio import Portfolio
from src.utils.kst_time import fmt_compact, is_business_day, prev_business_day
from src.utils.logger import get_logger

log = get_logger("backtest")

# === 백테스트 설정 ===
DEFAULT_LOOKBACK_YEARS = 5
UNIVERSE_TOP_N = 50
MAX_HOLDINGS = 5
SCORE_TECH_WEIGHT = 0.5
SCORE_FLOW_WEIGHT = 0.3
SCORE_CREDIT_WEIGHT = 0.2
MOMENTUM_DAYS = 60
FLOW_LOOKBACK_DAYS = 20


@dataclass
class BacktestConfig:
    end_date: date
    lookback_years: int = DEFAULT_LOOKBACK_YEARS
    initial_cash: float = 100_000_000.0
    universe_top_n: int = UNIVERSE_TOP_N
    max_holdings: int = MAX_HOLDINGS
    fee_bps: float = 15.0
    slippage_bps: float = 10.0


@dataclass
class BacktestResult:
    config: BacktestConfig
    portfolio: Portfolio
    metrics: dict[str, Any]
    benchmark_total_return_pct: float
    monthly_picks: list[dict[str, Any]] = field(default_factory=list)


def _month_starts(start: date, end: date) -> list[date]:
    """[start, end] 안의 매월 첫 영업일 list."""
    out: list[date] = []
    cur = date(start.year, start.month, 1)
    while cur <= end:
        d = cur
        while d <= end and not is_business_day(d):
            d += timedelta(days=1)
        if start <= d <= end:
            out.append(d)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return out


def _safe_universe(target: date, top_n: int) -> list[str]:
    from pykrx import stock as pykrx_stock

    out: list[tuple[str, int]] = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = pykrx_stock.get_market_cap_by_ticker(fmt_compact(target), market=market)
        except Exception as e:
            log.info(f"universe fetch 실패 {market} {target}: {e}")
            continue
        if df is None or df.empty:
            continue
        big = df[df["시가총액"] >= 500_000_000_000]
        out.extend((str(c), int(r["시가총액"])) for c, r in big.iterrows())
    out.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in out[:top_n]]


def _get_close(code: str, on: date) -> float | None:
    """on 직전 영업일 종가."""
    from pykrx import stock as pykrx_stock

    start = on - timedelta(days=10)
    try:
        df = pykrx_stock.get_market_ohlcv_by_date(fmt_compact(start), fmt_compact(on), code)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    return float(df["종가"].iloc[-1])


def _technical_score(code: str, on: date) -> float:
    """60일 모멘텀 → 0~1 정규화. (current / 60d_ago - 1) 를 ±50% → 0~1 매핑."""
    from pykrx import stock as pykrx_stock

    start = on - timedelta(days=MOMENTUM_DAYS * 2 + 10)
    try:
        df = pykrx_stock.get_market_ohlcv_by_date(fmt_compact(start), fmt_compact(on), code)
    except Exception:
        return 0.5
    if df is None or len(df) < MOMENTUM_DAYS:
        return 0.5
    cur = float(df["종가"].iloc[-1])
    past = float(df["종가"].iloc[-MOMENTUM_DAYS])
    if past <= 0:
        return 0.5
    momentum = (cur - past) / past
    # ±50% → 0~1
    return max(0.0, min(1.0, (momentum + 0.5) / 1.0))


def _flow_score(code: str, on: date) -> float:
    """외인+기관 동반 매수 비율 (최근 20일)."""
    from pykrx import stock as pykrx_stock

    start = on - timedelta(days=FLOW_LOOKBACK_DAYS * 2 + 10)
    try:
        df = pykrx_stock.get_market_trading_value_by_date(
            fmt_compact(start), fmt_compact(on), code
        )
    except Exception:
        return 0.5
    if df is None or df.empty:
        return 0.5
    fcol = next((c for c in df.columns if "외국인" in c and "기타" not in c), None)
    icol = next((c for c in df.columns if "기관" in c and "외" not in c), None)
    if not fcol or not icol:
        return 0.5
    recent = df.tail(FLOW_LOOKBACK_DAYS)
    co = ((recent[fcol] > 0) & (recent[icol] > 0)).sum()
    return float(co) / max(1, len(recent))


def _short_top10_codes(on: date) -> set[str]:
    from pykrx import stock as pykrx_stock

    out: set[str] = set()
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = pykrx_stock.get_shorting_value_by_ticker(fmt_compact(on), market=market)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        col = "거래대금" if "거래대금" in df.columns else df.columns[0]
        top = df.sort_values(col, ascending=False).head(10)
        out.update(str(c) for c in top.index)
    return out


def _composite_score(tech: float, flow: float, short_codes: set[str], code: str) -> float:
    credit = 0.0 if code in short_codes else 1.0
    return (
        SCORE_TECH_WEIGHT * tech
        + SCORE_FLOW_WEIGHT * flow
        + SCORE_CREDIT_WEIGHT * credit
    )


def _benchmark_return(start: date, end: date) -> float:
    """KOSPI 1001 동기간 총수익률 (%)."""
    from pykrx import stock as pykrx_stock

    try:
        df = pykrx_stock.get_index_ohlcv_by_date(fmt_compact(start), fmt_compact(end), "1001")
    except Exception:
        return 0.0
    if df is None or len(df) < 2:
        return 0.0
    return round((float(df["종가"].iloc[-1]) - float(df["종가"].iloc[0])) / float(df["종가"].iloc[0]) * 100, 2)


def run(config: BacktestConfig) -> BacktestResult:
    end = config.end_date
    start = date(end.year - config.lookback_years, end.month, 1)
    rebalance_dates = _month_starts(start, end)
    if not rebalance_dates:
        raise RuntimeError("rebalance dates empty")

    log.info(f"backtest {start} ~ {end}, rebalances={len(rebalance_dates)}")

    pf = Portfolio(
        initial_cash=config.initial_cash,
        fee_bps=config.fee_bps,
        slippage_bps=config.slippage_bps,
    )

    monthly_picks: list[dict[str, Any]] = []

    for i, rb in enumerate(rebalance_dates):
        # 청산: 직전 포지션 모두 매도 (현재가 기준)
        if pf.positions:
            cur_prices = {c: _get_close(c, rb) or 0 for c in list(pf.positions.keys())}
            cur_prices = {c: p for c, p in cur_prices.items() if p > 0}
            pf.close_all(rb, cur_prices)

        # 신규 universe + score
        universe = _safe_universe(rb, config.universe_top_n)
        if not universe:
            pf.mark(rb, {})
            continue

        short_codes = _short_top10_codes(rb)
        scored: list[tuple[str, float]] = []
        for code in universe:
            tech = _technical_score(code, rb)
            flow = _flow_score(code, rb)
            score = _composite_score(tech, flow, short_codes, code)
            scored.append((code, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        picks = scored[: config.max_holdings]

        # 균등 진입
        if picks:
            slot = pf.cash / len(picks)
            entered: list[str] = []
            for code, _ in picks:
                px = _get_close(code, rb)
                if px is None:
                    continue
                if pf.open(code, rb, px, slot):
                    entered.append(code)
            monthly_picks.append({
                "date": rb.isoformat(),
                "picks": entered,
                "scores": [round(s, 3) for _, s in picks],
            })

        # 일별 mark 는 무거우니 월말마다 1회
        last_prices = {c: _get_close(c, rb) or 0 for c in pf.positions.keys()}
        last_prices = {c: p for c, p in last_prices.items() if p > 0}
        pf.mark(rb, last_prices)

        log.info(
            f"  [{i+1}/{len(rebalance_dates)}] {rb} positions={len(pf.positions)} "
            f"equity≈{int(pf.market_value(last_prices)):,}"
        )

    # 마지막 청산
    if pf.positions:
        last_date = rebalance_dates[-1]
        cur = {c: _get_close(c, last_date) or 0 for c in list(pf.positions.keys())}
        cur = {c: p for c, p in cur.items() if p > 0}
        pf.close_all(last_date, cur)
        pf.mark(last_date, {})

    bench_pct = _benchmark_return(rebalance_dates[0], rebalance_dates[-1])
    metrics = compute_metrics(
        pf.equity_curve,
        pf.initial_cash,
        [t.return_pct for t in pf.trades],
        benchmark_total_return_pct=bench_pct,
    )

    return BacktestResult(
        config=config,
        portfolio=pf,
        metrics=metrics.__dict__,
        benchmark_total_return_pct=bench_pct,
        monthly_picks=monthly_picks,
    )
