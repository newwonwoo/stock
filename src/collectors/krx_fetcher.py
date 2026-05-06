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
  - fetch_usdkrw()                 : 원/달러 종가
  - resolve_market_data_date()     : 실제 데이터가 있는 가장 최근 영업일

휴장일 fallback: 모든 fetcher 가 빈/0/None 응답 시 직전 영업일로 재시도 (최대 10영업일).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd
from pykrx import stock as pykrx_stock

from src import config
from src.utils.kst_time import (
    fmt_compact,
    is_business_day,
    last_business_day,
    prev_business_day,
    today_kst,
)
from src.utils.logger import get_logger

log = get_logger("krx")

_FALLBACK_MAX_BACK_DAYS = 10  # fallback for market closed days


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


def _is_empty(result: Any) -> bool:
    """빈 응답 판별 — fallback for market closed days."""
    if result is None:
        return True
    if hasattr(result, "empty") and getattr(result, "empty"):
        return True
    if isinstance(result, (list, tuple, set, dict)) and not result:
        return True
    if isinstance(result, (int, float)) and result == 0:
        return True
    return False


def _fetch_with_fallback(
    fetch_fn,
    target_date: date | None = None,
    max_back_days: int = _FALLBACK_MAX_BACK_DAYS,
):
    """
    fallback for market closed days.

    fetch_fn(date) -> result. 빈/0/None 이면 직전 영업일로 최대 max_back_days 회 재시도.
    반환: (result, actual_date_used). 모두 실패 시 (마지막 result, last tried date).
    """
    if target_date is None:
        target_date = _resolve_date(None)
    last = None
    cur = last_business_day(target_date)
    for i in range(max_back_days):
        try:
            last = fetch_fn(cur)
        except Exception as e:
            log.info(f"_fetch_with_fallback 시도 {i} ({cur}) 예외: {e}")
            last = None
        if not _is_empty(last):
            return last, cur
        cur = prev_business_day(cur)
    return last, cur


def resolve_market_data_date(d: date | None = None) -> date:
    """
    헤더 표시용 (envelope.market_as_of). 실제로 데이터가 잡히는 가장 최근 영업일.
    KOSPI 지수 OHLCV 가 있으면 그 날짜, 없으면 last_business_day(_resolve_date).
    """
    target = _resolve_date(d)
    target = last_business_day(target)
    cur = target
    for _ in range(_FALLBACK_MAX_BACK_DAYS):
        try:
            df = pykrx_stock.get_index_ohlcv_by_date(
                fmt_compact(cur), fmt_compact(cur), "1001"
            )
        except Exception:
            df = None
        if df is not None and not df.empty:
            return cur
        cur = prev_business_day(cur)
    return target


def fetch_market_cap(d: date | None = None, market: str = "ALL") -> pd.DataFrame:
    """전종목 시총. 컬럼: 종가/시가총액/거래량/거래대금/상장주식수."""
    target = _resolve_date(d)

    def _call(day: date) -> pd.DataFrame:
        return pykrx_stock.get_market_cap_by_ticker(fmt_compact(day), market=market)

    df, used = _fetch_with_fallback(_call, target)  # fallback for market closed days
    log.info(
        f"market_cap fetched: req={target} used={used} market={market} rows={0 if df is None else len(df)}"
    )
    return df if df is not None else pd.DataFrame()


def _universe_via_fdr(min_cap: int) -> list[TickerInfo]:
    """FinanceDataReader fallback. naver/yahoo 스크레이프 → KRX 인증 wall 무관."""
    try:
        import FinanceDataReader as fdr
    except Exception as e:
        log.info(f"FDR import 실패: {e}")
        return []
    out: list[TickerInfo] = []
    for sym, market in (("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ")):
        try:
            df = fdr.StockListing(sym)
        except Exception as e:
            log.info(f"FDR StockListing({sym}) 실패: {e}")
            continue
        if df is None or df.empty:
            continue
        cap_col = next((c for c in df.columns if c in ("Marcap", "MarketCap", "시가총액")), None)
        code_col = next((c for c in df.columns if c in ("Code", "Symbol", "code")), None)
        name_col = next((c for c in df.columns if c in ("Name", "name", "종목명")), None)
        if not cap_col or not code_col:
            log.info(f"FDR {sym} 컬럼 매칭 실패 ({df.columns.tolist()})")
            continue
        big = df[df[cap_col].fillna(0) >= min_cap]
        for _, row in big.iterrows():
            out.append(
                TickerInfo(
                    code=str(row[code_col]).zfill(6),
                    name=str(row[name_col]) if name_col else str(row[code_col]),
                    market=market,
                    market_cap=int(row[cap_col]),
                )
            )
    log.info(f"FDR universe ≥ {min_cap:,}: {len(out)}")
    return out


def fetch_universe_by_market_cap(
    min_cap: int = config.MARKET_CAP_MIN,
    d: date | None = None,
) -> list[TickerInfo]:
    """시총 ≥ min_cap 종목 universe. KOSPI + KOSDAQ 모두.

    pykrx 우선 → 빈 응답이면 직전 영업일로 fallback (최대 10영업일) → 그래도 빈 list 면 FDR.
    """
    target = _resolve_date(d)
    out: list[TickerInfo] = []

    def _by_market(day: date, market: str) -> pd.DataFrame:
        try:
            df = pykrx_stock.get_market_cap_by_ticker(fmt_compact(day), market=market)
        except Exception as e:
            log.info(f"KRX market_cap fetch 실패 ({market}, {day}): {e}")
            return pd.DataFrame()
        if df is None or df.empty or "시가총액" not in df.columns:
            return pd.DataFrame()
        return df

    actual_date = target
    for market in ("KOSPI", "KOSDAQ"):
        df, used = _fetch_with_fallback(  # fallback for market closed days
            lambda day, m=market: _by_market(day, m),
            target,
        )
        if df is None or df.empty:
            log.info(f"KRX market_cap 빈/이상 응답 ({market}, target={target})")
            continue
        actual_date = used
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

    if not out:
        log.info("pykrx universe 비어있음 — FDR fallback 시도")
        out = _universe_via_fdr(min_cap)
    log.info(f"universe ≥ {min_cap:,}: {len(out)} tickers (target={target} used={actual_date})")
    return out


def _ohlcv_via_fdr(code: str, days: int, end: date) -> pd.DataFrame:
    """FDR fallback. naver finance OHLCV → 한국 컬럼명으로 normalize."""
    try:
        import FinanceDataReader as fdr
    except Exception:
        return pd.DataFrame()
    start = end - timedelta(days=days * 2 + 10)
    try:
        df = fdr.DataReader(code, start.isoformat(), end.isoformat())
    except Exception as e:
        log.info(f"FDR OHLCV 실패 {code}: {e}")
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    # FDR 컬럼: Open/High/Low/Close/Volume → pykrx 한글 컬럼으로 통일
    rename = {"Open": "시가", "High": "고가", "Low": "저가", "Close": "종가", "Volume": "거래량"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    return df.tail(days)


def fetch_ohlcv(code: str, days: int = 60, d: date | None = None) -> pd.DataFrame:
    """code 의 최근 days 영업일 OHLCV. pykrx 실패 시 FDR fallback.

    end 가 휴장일이면 직전 영업일로 fallback (최대 10영업일).
    """
    end = _resolve_date(d)

    def _call(day: date) -> pd.DataFrame:
        start = day - timedelta(days=days * 2 + 10)  # 휴일 여유
        try:
            df = pykrx_stock.get_market_ohlcv_by_date(
                fmt_compact(start), fmt_compact(day), code
            )
        except Exception as e:
            log.info(f"KRX OHLCV 실패 {code} day={day}: {e}")
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        return df

    df, used = _fetch_with_fallback(_call, end)  # fallback for market closed days
    if df is None or df.empty:
        return _ohlcv_via_fdr(code, days, end)
    return df.tail(days)


def fetch_credit_balance(d: date | None = None) -> pd.DataFrame:
    """종목별 신용잔고. KRX 신용대주 잔고. 실패 시 빈 DataFrame.

    fallback for market closed days: 직전 영업일로 최대 10회 재시도.
    """
    target = _resolve_date(d)
    fn = getattr(pykrx_stock, "get_shorting_balance_by_ticker", None)
    if fn is None:
        log.info("pykrx 에 get_shorting_balance_by_ticker 없음")
        return pd.DataFrame()

    def _call(day: date) -> pd.DataFrame:
        try:
            r = fn(fmt_compact(day))
        except Exception as e:
            log.info(f"KRX credit_balance 실패 day={day}: {e}")
            return pd.DataFrame()
        return r if r is not None else pd.DataFrame()

    df, _used = _fetch_with_fallback(_call, target)  # fallback for market closed days
    return df if df is not None else pd.DataFrame()


def fetch_short_top10(d: date | None = None) -> dict[str, list[dict[str, Any]]]:
    """공매도 거래대금 Top 10 (KOSPI/KOSDAQ 각각). 실패 시 빈 dict."""
    target = _resolve_date(d)
    out: dict[str, list[dict[str, Any]]] = {"KOSPI": [], "KOSDAQ": []}
    for market in ("KOSPI", "KOSDAQ"):

        def _call(day: date, m: str = market) -> pd.DataFrame:
            try:
                df = pykrx_stock.get_shorting_value_by_ticker(fmt_compact(day), market=m)
            except Exception as e:
                log.info(f"KRX short_top10 실패 ({m}, {day}): {e}")
                return pd.DataFrame()
            return df if df is not None else pd.DataFrame()

        df, _used = _fetch_with_fallback(_call, target)  # fallback for market closed days
        if df is None or df.empty:
            continue
        col = "거래대금" if "거래대금" in df.columns else (df.columns[0] if len(df.columns) else None)
        if col is None:
            continue
        top = df.sort_values(col, ascending=False).head(10)
        rows: list[dict[str, Any]] = []
        for code, row in top.iterrows():
            try:
                name = pykrx_stock.get_market_ticker_name(code)
            except Exception:
                name = str(code)
            rows.append({"code": str(code), "name": name, "short_value": int(row[col])})
        out[market] = rows
    log.info(f"short_top10: KOSPI={len(out.get('KOSPI', []))} KOSDAQ={len(out.get('KOSDAQ', []))}")
    return out


def fetch_investor_flow(code: str, days: int = 7, d: date | None = None) -> pd.DataFrame:
    """외인/기관/개인 일별 순매수 (단위: 원). 실패 시 빈 DataFrame.

    fallback for market closed days: end 가 휴장이면 직전 영업일로 최대 10회 재시도.
    """
    end = _resolve_date(d)

    def _call(day: date) -> pd.DataFrame:
        start = day - timedelta(days=days * 2 + 10)
        try:
            df = pykrx_stock.get_market_trading_value_by_date(
                fmt_compact(start), fmt_compact(day), code
            )
        except Exception as e:
            log.info(f"KRX investor_flow 실패 {code} day={day}: {e}")
            return pd.DataFrame()
        return df if df is not None else pd.DataFrame()

    df, _used = _fetch_with_fallback(_call, end)  # fallback for market closed days
    if df is None:
        return pd.DataFrame()
    return df.tail(days)


def fetch_foreign_ownership(code: str, days: int = 30, d: date | None = None) -> pd.DataFrame:
    """외인 보유율 (%) 일별 추이. 실패 시 빈 DataFrame.

    fallback for market closed days: end 가 휴장이면 직전 영업일로 최대 10회 재시도.
    """
    end = _resolve_date(d)

    def _call(day: date) -> pd.DataFrame:
        start = day - timedelta(days=days * 2 + 10)
        try:
            df = pykrx_stock.get_exhaustion_rates_of_foreign_investor(
                fmt_compact(start), fmt_compact(day), code
            )
        except Exception as e:
            log.info(f"KRX foreign_ownership 실패 {code} day={day}: {e}")
            return pd.DataFrame()
        return df if df is not None else pd.DataFrame()

    df, _used = _fetch_with_fallback(_call, end)  # fallback for market closed days
    if df is None:
        return pd.DataFrame()
    return df.tail(days)


def _index_change_via_fdr(fdr_symbol: str) -> float:
    """FDR fallback. KS11=KOSPI, KQ11=KOSDAQ."""
    try:
        import FinanceDataReader as fdr
    except Exception:
        return 0.0
    end = _resolve_date(None)
    start = end - timedelta(days=15)
    try:
        df = fdr.DataReader(fdr_symbol, start.isoformat(), end.isoformat())
    except Exception as e:
        log.info(f"FDR index {fdr_symbol} 실패: {e}")
        return 0.0
    if df is None or len(df) < 2 or "Close" not in df.columns:
        return 0.0
    last = float(df["Close"].iloc[-1])
    prev = float(df["Close"].iloc[-2])
    if prev <= 0:
        return 0.0
    return round((last - prev) / prev * 100, 2)


_INDEX_FDR_MAP = {"1001": "KS11", "2001": "KQ11"}


def fetch_index_change(index_ticker: str, d: date | None = None) -> float:
    """지수 ticker 의 직전 영업일 대비 변화율 (%). 1001=KOSPI, 2001=KOSDAQ.

    end 가 휴장이면 직전 영업일로 fallback (최대 10영업일).
    """
    end = _resolve_date(d)

    def _call(day: date) -> pd.DataFrame:
        start = day - timedelta(days=15)
        try:
            df = pykrx_stock.get_index_ohlcv_by_date(
                fmt_compact(start), fmt_compact(day), index_ticker
            )
        except Exception as e:
            log.info(f"index ohlcv 실패 {index_ticker} day={day}: {e}")
            return pd.DataFrame()
        # 변화율 계산 위해 최소 2 행 필요
        if df is None or len(df) < 2:
            return pd.DataFrame()
        return df

    df, _used = _fetch_with_fallback(_call, end)  # fallback for market closed days
    if df is None or len(df) < 2:
        fdr_sym = _INDEX_FDR_MAP.get(index_ticker)
        return _index_change_via_fdr(fdr_sym) if fdr_sym else 0.0
    last = float(df["종가"].iloc[-1])
    prev = float(df["종가"].iloc[-2])
    if prev <= 0:
        return 0.0
    return round((last - prev) / prev * 100, 2)


def fetch_kospi_foreign_net(d: date | None = None) -> float:
    """KOSPI 시장 전체 외인 순매수 (당일, 원). 미지원 시 0.

    fallback for market closed days: 휴장이면 직전 영업일로 최대 10회 재시도.
    """
    end = _resolve_date(d)
    fn = getattr(pykrx_stock, "get_market_trading_value_by_investor", None)
    if fn is None:
        return 0.0

    def _call(day: date) -> float:
        try:
            df = fn(fmt_compact(day), fmt_compact(day), "KOSPI")
        except Exception as e:
            log.info(f"market trading value 실패 day={day}: {e}")
            return 0.0
        if df is None or df.empty:
            return 0.0
        foreign_col = next(
            (c for c in df.columns if "외국인" in c and "기타" not in c), None
        )
        if not foreign_col:
            return 0.0
        try:
            return float(df[foreign_col].sum())
        except Exception:
            return 0.0

    val, _used = _fetch_with_fallback(_call, end)  # fallback for market closed days
    return float(val) if val is not None else 0.0


def _usdkrw_via_fdr(end: date) -> float:
    """FDR USD/KRW (FX) 종가. 휴장일 fallback 까지 처리."""
    try:
        import FinanceDataReader as fdr
    except Exception:
        return 0.0
    start = end - timedelta(days=20)
    try:
        df = fdr.DataReader("USD/KRW", start.isoformat(), end.isoformat())
    except Exception as e:
        log.info(f"FDR USD/KRW 실패: {e}")
        return 0.0
    if df is None or df.empty or "Close" not in df.columns:
        return 0.0
    try:
        return float(df["Close"].dropna().iloc[-1])
    except Exception:
        return 0.0


def fetch_usdkrw(d: date | None = None) -> float:
    """원/달러 종가. pykrx → FDR fallback. fallback for market closed days.

    pykrx 의 get_exhaustion_rates_of_foreign_investor 와 별개. pykrx 에는 FX 가
    없으므로 FDR 위주. 빈 응답 가정 시 직전 영업일로 최대 10회 재시도.
    """
    end = _resolve_date(d)
    cur = last_business_day(end)
    for _ in range(_FALLBACK_MAX_BACK_DAYS):
        v = _usdkrw_via_fdr(cur)
        if v and v > 0:
            return round(v, 2)
        cur = prev_business_day(cur)
    return 0.0
