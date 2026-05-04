"""
KRX 데이터 수집기 (pykrx 기반).

키/한도 없음 (KRX 공식 페이지 스크레이핑). 봇 KIS 한도 절약 목적.

제공:
  - fetch_market_cap(date)         : 전종목 시총 DataFrame
  - fetch_universe_by_market_cap() : 시총 ≥ 5천억 종목 리스트
  - fetch_ohlcv(code, days)        : 일봉
  - fetch_credit_balance(date)     : 종목별 신용잔고
  - fetch_short_top10(date)        : KOSPI/KOSDAQ 공매도 거래대금 Top 10
  - fetch_investor_flow(code, days): 외인/기관/개인 일별 순매수
  - fetch_foreign_ownership(code, days): 외인 보유율 추이
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd
from pykrx import stock as pykrx_stock

from src import config
from src.utils.kst_time import fmt_compact, prev_business_day, today_kst
from src.utils.logger import get_logger

log = get_logger("krx")


@dataclass
class TickerInfo:
    code: str
    name: str
    market: str  # "KOSPI" | "KOSDAQ"
    market_cap: int


def _resolve_date(d: date | None) -> date:
    """date 미지정 시 가장 최근 영업일 반환."""
    if d is None:
        td = today_kst()
        return td if _is_today_settled(td) else prev_business_day(td)
    return d


def _is_today_settled(d: date) -> bool:
    """오늘이 영업일이고 장 마감 후인지. 보수적으로 16:00 KST 이후만 True."""
    from src.utils.kst_time import is_business_day, now_kst

    if not is_business_day(d):
        return False
    n = now_kst()
    return n.date() != d or n.hour >= 16


def fetch_market_cap(d: date | None = None, market: str = "ALL") -> pd.DataFrame:
    """전종목 시총. 컬럼: 종가/시가총액/거래량/거래대금/상장주식수."""
    target = _resolve_date(d)
    df = pykrx_stock.get_market_cap_by_ticker(fmt_compact(target), market=market)
    log.info(f"market_cap fetched: date={target} market={market} rows={len(df)}")
    return df


def fetch_universe_by_market_cap(
    min_cap: int = config.MARKET_CAP_MIN,
    d: date | None = None,
) -> list[TickerInfo]:
    """시총 ≥ min_cap 종목 universe. KOSPI + KOSDAQ 모두.

    KRX 측 일시적 오류 / 인증 wall 이면 빈 list 반환 (호출자가 fallback).
    """
    target = _resolve_date(d)
    out: list[TickerInfo] = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = pykrx_stock.get_market_cap_by_ticker(fmt_compact(target), market=market)
        except Exception as e:
            log.info(f"KRX market_cap fetch 실패 ({market}, {target}): {e}")
            continue
        if df is None or df.empty or "시가총액" not in df.columns:
            log.info(f"KRX market_cap 빈/이상 응답 ({market}, {target})")
            continue
        big = df[df["시가총액"] >= min_cap]
        for code, row in big.iterrows():
            try:
                name = pykrx_stock.get_market_ticker_name(code)
            except Exception:
                name = str(code)
            out.append(
                TickerInfo(
                    code=str(code),
                    name=name,
                    market=market,
                    market_cap=int(row["시가총액"]),
                )
            )
    log.info(f"universe ≥ {min_cap:,}: {len(out)} tickers ({target})")
    return out


def fetch_ohlcv(code: str, days: int = 60, d: date | None = None) -> pd.DataFrame:
    """code 의 최근 days 영업일 OHLCV."""
    end = _resolve_date(d)
    start = end - timedelta(days=days * 2 + 10)  # 휴일 여유
    df = pykrx_stock.get_market_ohlcv_by_date(fmt_compact(start), fmt_compact(end), code)
    return df.tail(days)


def fetch_credit_balance(d: date | None = None) -> pd.DataFrame:
    """종목별 신용잔고. KRX 신용대주 잔고."""
    target = _resolve_date(d)
    # pykrx: stock.get_shorting_balance_by_ticker / get_market_credit_balance 패턴
    # API 명은 버전마다 다름. 우선 ticker 별 잔고 시도.
    fn = getattr(pykrx_stock, "get_shorting_balance_by_ticker", None)
    if fn is None:
        raise RuntimeError("pykrx 에 get_shorting_balance_by_ticker 없음. 버전 확인 필요")
    df = fn(fmt_compact(target))
    return df


def fetch_short_top10(d: date | None = None) -> dict[str, list[dict[str, Any]]]:
    """공매도 거래대금 Top 10 (KOSPI/KOSDAQ 각각)."""
    target = _resolve_date(d)
    out: dict[str, list[dict[str, Any]]] = {}
    for market in ("KOSPI", "KOSDAQ"):
        df = pykrx_stock.get_shorting_value_by_ticker(fmt_compact(target), market=market)
        # 거래대금 컬럼 이름은 pykrx 버전에 따라 "거래대금" 또는 "공매도거래대금".
        col = "거래대금" if "거래대금" in df.columns else df.columns[0]
        top = df.sort_values(col, ascending=False).head(10)
        out[market] = [
            {
                "code": str(code),
                "name": pykrx_stock.get_market_ticker_name(code),
                "short_value": int(row[col]),
            }
            for code, row in top.iterrows()
        ]
    log.info(f"short_top10: KOSPI={len(out.get('KOSPI', []))} KOSDAQ={len(out.get('KOSDAQ', []))}")
    return out


def fetch_investor_flow(code: str, days: int = 7, d: date | None = None) -> pd.DataFrame:
    """외인/기관/개인 일별 순매수 (단위: 원)."""
    end = _resolve_date(d)
    start = end - timedelta(days=days * 2 + 10)
    df = pykrx_stock.get_market_trading_value_by_date(
        fmt_compact(start), fmt_compact(end), code
    )
    return df.tail(days)


def fetch_foreign_ownership(code: str, days: int = 30, d: date | None = None) -> pd.DataFrame:
    """외인 보유율 (%) 일별 추이."""
    end = _resolve_date(d)
    start = end - timedelta(days=days * 2 + 10)
    df = pykrx_stock.get_exhaustion_rates_of_foreign_investor(
        fmt_compact(start), fmt_compact(end), code
    )
    return df.tail(days)


def fetch_index_change(index_ticker: str, d: date | None = None) -> float:
    """지수 ticker 의 직전 영업일 대비 변화율 (%). 1001=KOSPI, 2001=KOSDAQ."""
    end = _resolve_date(d)
    start = end - timedelta(days=15)
    try:
        df = pykrx_stock.get_index_ohlcv_by_date(fmt_compact(start), fmt_compact(end), index_ticker)
    except Exception as e:
        log.info(f"index ohlcv 실패 {index_ticker}: {e}")
        return 0.0
    if df is None or len(df) < 2:
        return 0.0
    last = float(df["종가"].iloc[-1])
    prev = float(df["종가"].iloc[-2])
    if prev <= 0:
        return 0.0
    return round((last - prev) / prev * 100, 2)


def fetch_kospi_foreign_net(d: date | None = None) -> float:
    """KOSPI 시장 전체 외인 순매수 (당일, 원). 미지원 시 0."""
    end = _resolve_date(d)
    fn = getattr(pykrx_stock, "get_market_trading_value_by_investor", None)
    if fn is None:
        return 0.0
    try:
        df = fn(fmt_compact(end), fmt_compact(end), "KOSPI")
    except Exception as e:
        log.info(f"market trading value 실패: {e}")
        return 0.0
    if df is None or df.empty:
        return 0.0
    foreign_col = next((c for c in df.columns if "외국인" in c and "기타" not in c), None)
    if not foreign_col:
        return 0.0
    try:
        return float(df[foreign_col].sum())
    except Exception:
        return 0.0
