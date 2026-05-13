"""
NPS 신규편입 이벤트 스터디 — D+0/+5/+30/+90/+180 KOSPI 초과수익 검증.

설계:
  1) 시총 상위 N (universe_top_n) 종목 추림
  2) 각 종목의 DART majorstock 응답 → NPS 첫 보고 일자 (first_buy_de) 추출
     - bsis_de (변동 기준일) 가 분석 기간 (lookback_years) 내인 것만 채택
     - 5%↑ 보고 의무 발생 시점 — 즉 NPS 가 5% 도달한 시점 (정확한 '첫 매수일' 은 아님)
  3) 각 이벤트의 종목 OHLCV + KOSPI OHLCV 로 절대수익 + KOSPI 대비 초과수익 계산
  4) 윈도우: D-1 (편입일 직전 종가) 기준 → D+5, +30, +90, +180 종가
  5) 분포 + 평균/중위 + 양수비율 집계 → md/json 리포트

env:
  BACKTEST_NPS_UNIVERSE_TOP_N    default 200
  BACKTEST_NPS_LOOKBACK_YEARS    default 3
  BACKTEST_NPS_END_DATE          default today
  BACKTEST_NPS_MIN_BUFFER_DAYS   default 180   (편입일+이 기간만큼 OHLCV 확보 가능해야 채택)

호출 한도:
  - DART majorstock: universe N 만큼. 200 종목 ≈ 200 API call. DART 일 한도 10,000 여유.
  - KRX OHLCV: 2N 호출 (종목 + KOSPI 1회). 시간 부담 큼 — universe_top_n 100~200 권장.

실행 환경:
  - Korean IP 필수 (pykrx KRX wall). 자체 호스트 러너 또는 한국 VPS 에서만.
  - DART_API_KEY 필요.

출력:
  out/backtest_nps_events_YYYY-MM-DD.md  (사람 읽기용)
  out/backtest_nps_events_YYYY-MM-DD.json (raw)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from statistics import median

from src import config
from src.collectors.dart_corp_cache import load_or_refresh as load_corp_codes
from src.collectors.dart_fetcher import DartFetcher
from src.collectors.dart_financials import extract_nps_holding_change
from src.collectors.krx_fetcher import fetch_universe_by_market_cap
from src.utils.kst_time import today_kst
from src.utils.logger import get_logger

log = get_logger("backtest_nps")

WINDOWS = (5, 30, 90, 180)  # 영업일 아닌 캘린더일 (단순화)


@dataclass
class EventResult:
    code: str
    name: str
    first_buy_de: str
    base_price: float
    base_date: str
    kospi_base: float
    abs_returns: dict[int, float] = field(default_factory=dict)
    excess_returns: dict[int, float] = field(default_factory=dict)


def _parse_iso(s: str) -> date | None:
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _price_on_or_before(df, target: date) -> tuple[date, float] | None:
    """종가 OHLCV DataFrame (pykrx 한글 컬럼) 에서 target 일자 또는 그 이전 가장 가까운 영업일 종가.

    df.index 는 Timestamp. '종가' 컬럼 사용.
    """
    if df is None or df.empty or "종가" not in df.columns:
        return None
    # 가능한 한 직전 영업일 종가 (target 이 휴장이면 그 이전 종가)
    target_ts = datetime.combine(target, datetime.min.time())
    try:
        sub = df[df.index <= target_ts]
    except Exception:
        return None
    if sub.empty:
        return None
    last = sub.iloc[-1]
    last_date = sub.index[-1].date() if hasattr(sub.index[-1], "date") else target
    return last_date, float(last["종가"])


def _fetch_ohlcv_range(code: str, start: date, end: date):
    """code 의 [start, end] OHLCV. pykrx 직접 호출 (fetch_ohlcv 의 tail() 동작 회피)."""
    from pykrx import stock as pykrx_stock
    from src.utils.kst_time import fmt_compact

    try:
        df = pykrx_stock.get_market_ohlcv_by_date(
            fmt_compact(start), fmt_compact(end), code
        )
    except Exception as e:
        log.info(f"OHLCV fail {code} {start}~{end}: {e}")
        return None
    return df


def _fetch_kospi_index_range(start: date, end: date):
    """KOSPI 지수 (1001) OHLCV."""
    from pykrx import stock as pykrx_stock
    from src.utils.kst_time import fmt_compact

    try:
        return pykrx_stock.get_index_ohlcv_by_date(
            fmt_compact(start), fmt_compact(end), "1001"
        )
    except Exception as e:
        log.info(f"KOSPI index fail {start}~{end}: {e}")
        return None


def _build_event(
    code: str,
    name: str,
    first_buy: date,
    kospi_df,
) -> EventResult | None:
    """단일 이벤트 — base = first_buy 직전 종가, +window 종가들로 abs/excess."""
    end = first_buy + timedelta(days=max(WINDOWS) + 30)
    start = first_buy - timedelta(days=10)
    stock = _fetch_ohlcv_range(code, start, end)
    base = _price_on_or_before(stock, first_buy - timedelta(days=1))
    if base is None:
        log.info(f"base price 없음 {code} {first_buy}")
        return None
    base_date, base_price = base

    kospi_base = _price_on_or_before(kospi_df, base_date)
    if kospi_base is None:
        return None
    _, kospi_base_val = kospi_base

    ev = EventResult(
        code=code,
        name=name,
        first_buy_de=first_buy.isoformat(),
        base_price=base_price,
        base_date=base_date.isoformat(),
        kospi_base=kospi_base_val,
    )
    for w in WINDOWS:
        sp = _price_on_or_before(stock, first_buy + timedelta(days=w))
        kp = _price_on_or_before(kospi_df, first_buy + timedelta(days=w))
        if sp is None or kp is None:
            continue
        abs_ret = (sp[1] - base_price) / base_price * 100
        kospi_ret = (kp[1] - kospi_base_val) / kospi_base_val * 100
        ev.abs_returns[w] = round(abs_ret, 2)
        ev.excess_returns[w] = round(abs_ret - kospi_ret, 2)
    return ev if ev.excess_returns else None


def _summary_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    pos = [v for v in values if v > 0]
    return {
        "n": len(values),
        "mean": round(sum(values) / len(values), 2),
        "median": round(median(values), 2),
        "positive_pct": round(len(pos) / len(values) * 100, 1),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
    }


def run() -> dict:
    universe_top_n = int(os.environ.get("BACKTEST_NPS_UNIVERSE_TOP_N", "200"))
    lookback_years = int(os.environ.get("BACKTEST_NPS_LOOKBACK_YEARS", "3"))
    min_buffer = int(os.environ.get("BACKTEST_NPS_MIN_BUFFER_DAYS", "180"))
    end_s = os.environ.get("BACKTEST_NPS_END_DATE", "")
    end_date = date.fromisoformat(end_s) if end_s else today_kst()
    earliest = end_date - timedelta(days=lookback_years * 365)
    cutoff_latest = end_date - timedelta(days=min_buffer)

    log.info(
        f"config: top_n={universe_top_n} years={lookback_years} "
        f"window=[{earliest}, {cutoff_latest}]"
    )

    universe = fetch_universe_by_market_cap()
    universe.sort(key=lambda t: t.market_cap, reverse=True)
    universe = universe[:universe_top_n]
    log.info(f"universe: {len(universe)}")

    corp_map = load_corp_codes()
    fetcher = DartFetcher()

    kospi_df = _fetch_kospi_index_range(earliest - timedelta(days=10), end_date)
    if kospi_df is None or kospi_df.empty:
        raise RuntimeError("KOSPI index OHLCV 비어있음 — Korean IP 인지 확인")

    events: list[EventResult] = []
    skipped = {"no_corp": 0, "no_nps": 0, "out_of_window": 0, "no_price": 0}

    for i, t in enumerate(universe):
        corp_code = corp_map.get(t.code)
        if not corp_code:
            skipped["no_corp"] += 1
            continue
        try:
            major = fetcher.fetch_major_stock_changes(corp_code)
        except Exception as e:
            log.info(f"DART major fetch fail {t.code}: {e}")
            continue
        nps = extract_nps_holding_change(major)
        if not nps.first_buy_de:
            skipped["no_nps"] += 1
            continue
        fb = _parse_iso(nps.first_buy_de)
        if fb is None:
            skipped["no_nps"] += 1
            continue
        if fb < earliest or fb > cutoff_latest:
            skipped["out_of_window"] += 1
            continue
        ev = _build_event(t.code, t.name, fb, kospi_df)
        if ev is None:
            skipped["no_price"] += 1
            continue
        events.append(ev)
        if (i + 1) % 25 == 0:
            log.info(f"progress {i+1}/{len(universe)} events={len(events)}")

    log.info(f"events collected: {len(events)} skipped={skipped}")

    abs_by_w = {w: [e.abs_returns[w] for e in events if w in e.abs_returns] for w in WINDOWS}
    exc_by_w = {w: [e.excess_returns[w] for e in events if w in e.excess_returns] for w in WINDOWS}

    summary = {
        "config": {
            "universe_top_n": universe_top_n,
            "lookback_years": lookback_years,
            "end_date": end_date.isoformat(),
            "min_buffer_days": min_buffer,
            "earliest": earliest.isoformat(),
            "cutoff_latest": cutoff_latest.isoformat(),
        },
        "events_count": len(events),
        "skipped": skipped,
        "abs_returns": {f"+{w}d": _summary_stats(abs_by_w[w]) for w in WINDOWS},
        "excess_returns_vs_kospi": {f"+{w}d": _summary_stats(exc_by_w[w]) for w in WINDOWS},
        "events": [asdict(e) for e in events],
    }
    return summary


def _format_md(summary: dict) -> str:
    cfg = summary["config"]
    lines = [
        f"# NPS 신규편입 이벤트 스터디 — {cfg['end_date']}",
        "",
        f"- universe: 시총 상위 {cfg['universe_top_n']}",
        f"- lookback: {cfg['earliest']} ~ {cfg['cutoff_latest']}",
        f"- 이벤트 채택 수: **{summary['events_count']}**",
        f"- skipped: {summary['skipped']}",
        "",
        "## 절대수익 (편입일 직전 종가 → D+N 종가)",
        "",
        "| 윈도우 | n | 평균 | 중위 | 양수비율 | 최저 | 최고 |",
        "|---|---|---|---|---|---|---|",
    ]
    for w in WINDOWS:
        s = summary["abs_returns"][f"+{w}d"]
        if s["n"] == 0:
            lines.append(f"| +{w}d | 0 | - | - | - | - | - |")
        else:
            lines.append(
                f"| +{w}d | {s['n']} | {s['mean']}% | {s['median']}% | "
                f"{s['positive_pct']}% | {s['min']}% | {s['max']}% |"
            )
    lines += [
        "",
        "## KOSPI 대비 초과수익",
        "",
        "| 윈도우 | n | 평균 | 중위 | 양수비율 | 최저 | 최고 |",
        "|---|---|---|---|---|---|---|",
    ]
    for w in WINDOWS:
        s = summary["excess_returns_vs_kospi"][f"+{w}d"]
        if s["n"] == 0:
            lines.append(f"| +{w}d | 0 | - | - | - | - | - |")
        else:
            lines.append(
                f"| +{w}d | {s['n']} | {s['mean']}% | {s['median']}% | "
                f"{s['positive_pct']}% | {s['min']}% | {s['max']}% |"
            )

    events = summary.get("events", [])
    # +90d 기준 top/bottom 5
    by_90 = [e for e in events if "90" in {str(k) for k in e.get("excess_returns", {}).keys()} or 90 in e.get("excess_returns", {})]
    by_90.sort(key=lambda e: e.get("excess_returns", {}).get(90, e.get("excess_returns", {}).get("90", 0)), reverse=True)
    if by_90:
        lines += ["", "## Top 5 초과수익 (+90d)", ""]
        for e in by_90[:5]:
            er = e["excess_returns"]
            v = er.get(90, er.get("90"))
            lines.append(f"- {e['name']} ({e['code']}) 편입 {e['first_buy_de']} → +90d 초과 {v}%")
        lines += ["", "## Bottom 5 초과수익 (+90d)", ""]
        for e in by_90[-5:]:
            er = e["excess_returns"]
            v = er.get(90, er.get("90"))
            lines.append(f"- {e['name']} ({e['code']}) 편입 {e['first_buy_de']} → +90d 초과 {v}%")

    lines += [
        "",
        "## 해석 가이드",
        "",
        "- DART 5% 보고는 NPS 가 시총의 5% 도달했을 때만 발생 → '첫 매수일' 보다 실제로는 좀 더 늦은 시점.",
        "- 즉 본 분석의 first_buy_de 는 'NPS 가 시장에 노출된 첫 시점' 으로 해석.",
        "- 양수비율 60% 이상 + 평균 > 0 이면 통계적으로 의미 있는 시그널.",
        "- +30~+90d 가 가장 강한 구간일 가능성 높음 (편입 모멘텀 + 분기별 비중 확대).",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    summary = run()
    out_dir = config.OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = summary["config"]["end_date"]
    json_path = out_dir / f"backtest_nps_events_{stamp}.json"
    md_path = out_dir / f"backtest_nps_events_{stamp}.md"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_format_md(summary), encoding="utf-8")
    log.info(f"report: {md_path}")
    log.info(f"raw:    {json_path}")
    # 요약 출력
    for w in WINDOWS:
        s = summary["excess_returns_vs_kospi"][f"+{w}d"]
        if s.get("n", 0):
            log.info(
                f"excess +{w}d: n={s['n']} mean={s['mean']}% median={s['median']}% pos={s['positive_pct']}%"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
