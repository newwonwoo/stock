"""
핫섹터 알림 — 포괄 점수제 (거래대금 + 외인 + 기관 가중 합).

지표 (모두 최근 3영업일 vs 그 이전 3영업일):
  1. 거래대금 증가율          (가중치 0.5) ← 핵심
  2. 외인 순매수 (3일 합)     (가중치 0.3)
  3. 기관 순매수 (3일 합)     (가중치 0.2)

포괄 score = w_value × norm(value_growth) + w_foreign × norm(foreign_pct) + w_inst × norm(inst_pct)
- norm(x) = clip(x / 50, -1, 1)  (50% 변동 = ±1.0)
- 양수 = HOT 후보, 음수 = COLD 후보

성능 절충:
  - 섹터 구성 종목 중 시총 상위 CONSTITUENTS_TOP_N 만 합산 (외인/기관)
  - 거래대금은 섹터 지수 자체 데이터 사용 (가능 시) → fallback: 구성 종목 합

가중치는 노출 → 튜닝 가능.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from src.utils.kst_time import fmt_compact, prev_business_day, today_kst
from src.utils.logger import get_logger

log = get_logger("hot_sectors")

# === 가중치 (튜닝 대상) ===
VALUE_WEIGHT = 0.5
FOREIGN_WEIGHT = 0.3
INSTITUTION_WEIGHT = 0.2

LOOKBACK_RECENT = 3
LOOKBACK_PREV = 3
CONSTITUENTS_TOP_N = 5
NORM_SPAN_PCT = 50.0   # ±50% = ±1.0

NON_SECTOR_TICKERS = {
    "1001", "1002", "1003", "1004", "1028", "1034", "1035",
    "2001", "2002", "2003", "2004", "2203",
}

HOT_TOP_N = 3
COLD_BOTTOM_N = 3


@dataclass
class SectorScore:
    code: str
    name: str
    market: str
    value_recent: float       # 최근 3일 거래대금 합 (원)
    value_prev: float         # 그 이전 3일 거래대금 합 (원)
    value_growth_pct: float
    foreign_net_3d: float     # 외인 순매수 합 (원, 시총상위 구성종목 기준)
    inst_net_3d: float        # 기관 순매수 합
    foreign_pct: float        # 외인 / 시총상위 합 시총 (%)
    inst_pct: float
    composite_score: float
    last_close: float
    change_3d_pct: float


def _safe_pct(end_val: float, start_val: float) -> float:
    if not start_val:
        return 0.0
    return round((end_val - start_val) / abs(start_val) * 100, 2)


def _norm(x: float, span: float = NORM_SPAN_PCT) -> float:
    return max(-1.0, min(1.0, x / span))


def _composite(value_growth: float, foreign_pct: float, inst_pct: float) -> float:
    return round(
        VALUE_WEIGHT * _norm(value_growth)
        + FOREIGN_WEIGHT * _norm(foreign_pct)
        + INSTITUTION_WEIGHT * _norm(inst_pct),
        4,
    )


def _sector_value_growth(ticker: str, end: date) -> tuple[float, float, float, float, float]:
    """섹터 지수 6영업일 데이터 → (recent_sum, prev_sum, growth_pct, last_close, change_3d_pct)."""
    from pykrx import stock as pykrx_stock

    start = end - timedelta(days=20)
    df = pykrx_stock.get_index_ohlcv_by_date(fmt_compact(start), fmt_compact(end), ticker)
    if df is None or df.empty:
        return (0.0, 0.0, 0.0, 0.0, 0.0)

    val_col = "거래대금" if "거래대금" in df.columns else None
    closes = df["종가"]

    last_close = float(closes.iloc[-1])
    if len(closes) >= 7:
        change_3d = _safe_pct(last_close, float(closes.iloc[-4]))
    else:
        change_3d = 0.0

    if val_col is None or len(df) < 6:
        return (0.0, 0.0, 0.0, last_close, change_3d)

    recent = float(df[val_col].iloc[-LOOKBACK_RECENT:].sum())
    prev = float(df[val_col].iloc[-(LOOKBACK_RECENT + LOOKBACK_PREV):-LOOKBACK_RECENT].sum())
    growth = _safe_pct(recent, prev)
    return (recent, prev, growth, last_close, change_3d)


def _sector_constituents(ticker: str, target: date) -> list[str]:
    """섹터 지수 구성 종목 ticker 리스트 (시총 내림차순). pykrx 미지원 시 [] 반환."""
    from pykrx import stock as pykrx_stock

    fn = getattr(pykrx_stock, "get_index_portfolio_deposit_file", None)
    if fn is None:
        return []
    try:
        codes = fn(ticker, fmt_compact(target))
    except Exception:
        return []
    if not codes:
        return []

    # 시총 상위 N
    try:
        cap_df = pykrx_stock.get_market_cap_by_ticker(fmt_compact(target))
    except Exception:
        return list(codes)[:CONSTITUENTS_TOP_N]
    cap = {str(idx): int(row["시가총액"]) for idx, row in cap_df.iterrows()}
    sorted_codes = sorted(codes, key=lambda c: cap.get(str(c), 0), reverse=True)
    return [str(c) for c in sorted_codes[:CONSTITUENTS_TOP_N]]


def _sector_investor_flow(constituents: list[str], end: date) -> tuple[float, float, float]:
    """
    구성 종목 시총상위 N 의 최근 3영업일 외인/기관 순매수 합 + 시총 합.
    → (foreign_net_3d, inst_net_3d, total_market_cap_topN)
    """
    if not constituents:
        return (0.0, 0.0, 0.0)
    from pykrx import stock as pykrx_stock

    start = end - timedelta(days=10)
    foreign_sum = 0.0
    inst_sum = 0.0
    cap_sum = 0.0

    try:
        cap_df = pykrx_stock.get_market_cap_by_ticker(fmt_compact(end))
    except Exception:
        cap_df = None

    for code in constituents:
        if cap_df is not None and code in cap_df.index:
            cap_sum += float(cap_df.loc[code, "시가총액"])
        try:
            df = pykrx_stock.get_market_trading_value_by_date(
                fmt_compact(start), fmt_compact(end), code
            )
        except Exception:
            continue
        if df is None or df.empty:
            continue
        foreign_col = next((c for c in df.columns if "외국인" in c and "기타" not in c), None)
        inst_col = next((c for c in df.columns if "기관" in c and "외" not in c), None)
        if foreign_col:
            foreign_sum += float(df[foreign_col].iloc[-LOOKBACK_RECENT:].sum())
        if inst_col:
            inst_sum += float(df[inst_col].iloc[-LOOKBACK_RECENT:].sum())

    return (foreign_sum, inst_sum, cap_sum)


def compute_sector_score(ticker: str, name: str, market: str, target: date) -> SectorScore | None:
    val_recent, val_prev, val_growth, last_close, change_3d = _sector_value_growth(ticker, target)
    constituents = _sector_constituents(ticker, target)
    foreign_net, inst_net, cap_total = _sector_investor_flow(constituents, target)

    foreign_pct = round((foreign_net / cap_total * 100), 4) if cap_total else 0.0
    inst_pct = round((inst_net / cap_total * 100), 4) if cap_total else 0.0
    composite = _composite(val_growth, foreign_pct, inst_pct)

    return SectorScore(
        code=ticker,
        name=name,
        market=market,
        value_recent=val_recent,
        value_prev=val_prev,
        value_growth_pct=val_growth,
        foreign_net_3d=foreign_net,
        inst_net_3d=inst_net,
        foreign_pct=foreign_pct,
        inst_pct=inst_pct,
        composite_score=composite,
        last_close=last_close,
        change_3d_pct=change_3d,
    )


def fetch_sector_scores(target: date | None = None) -> list[SectorScore]:
    from pykrx import stock as pykrx_stock

    target = target or prev_business_day(today_kst() + timedelta(days=1))
    out: list[SectorScore] = []
    for market in ("KOSPI", "KOSDAQ"):
        try:
            tickers = pykrx_stock.get_index_ticker_list(date=fmt_compact(target), market=market)
        except Exception as e:
            log.info(f"index list 실패 {market}: {e}")
            continue
        for tk in tickers:
            if tk in NON_SECTOR_TICKERS:
                continue
            try:
                name = pykrx_stock.get_index_ticker_name(tk)
            except Exception:
                continue
            try:
                s = compute_sector_score(tk, name, market, target)
            except Exception as e:
                log.info(f"sector score 실패 {tk} {name}: {e}")
                continue
            if s is not None:
                out.append(s)
    log.info(f"sector composite scores: {len(out)} sectors ({target})")
    return out


def classify_hot_cold(scores: list[SectorScore]) -> dict[str, list[SectorScore]]:
    by_score = sorted(scores, key=lambda s: s.composite_score, reverse=True)
    return {
        "hot": by_score[:HOT_TOP_N],
        "cold": by_score[-COLD_BOTTOM_N:][::-1] if len(by_score) >= COLD_BOTTOM_N else [],
    }


def _to_dict(s: SectorScore) -> dict[str, Any]:
    return {
        "code": s.code,
        "name": s.name,
        "market": s.market,
        "composite_score": s.composite_score,
        "value_growth_pct": s.value_growth_pct,
        "foreign_net_3d": s.foreign_net_3d,
        "inst_net_3d": s.inst_net_3d,
        "foreign_pct": s.foreign_pct,
        "inst_pct": s.inst_pct,
        "change_3d_pct": s.change_3d_pct,
    }


def generate(target: date | None = None) -> dict[str, Any]:
    target = target or prev_business_day(today_kst() + timedelta(days=1))
    scores = fetch_sector_scores(target)
    classified = classify_hot_cold(scores)

    return {
        "date": target.isoformat(),
        "weights": {
            "value": VALUE_WEIGHT,
            "foreign": FOREIGN_WEIGHT,
            "institution": INSTITUTION_WEIGHT,
        },
        "lookback_business_days": LOOKBACK_RECENT,
        "hot_sectors": [_to_dict(s) for s in classified["hot"]],
        "cold_sectors": [_to_dict(s) for s in classified["cold"]],
        "all_sectors": [_to_dict(s) for s in scores],
    }


def hot_sector_codes(scores: list[SectorScore]) -> set[str]:
    return {s.code for s in classify_hot_cold(scores)["hot"]}
