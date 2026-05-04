"""
DART 재무 응답 → 분석기 입력 변환.

핵심 함수:
  - get_annual_snapshot(fetcher, corp_code, year) → AnnualSnapshot
  - get_recent_annuals(fetcher, corp_code, years=2) → list[AnnualSnapshot]
  - extract_nps_holding_change(records) → (prev_pct, curr_pct)

DART account_nm 매칭 키워드 (한국어 IFRS):
  - 매출: "매출액" / "수익(매출액)" / "영업수익"
  - 영익: "영업이익" / "영업이익(손실)"
  - 당기순이익: "당기순이익" / "분기순이익"
  - 영업현금흐름: "영업활동" + "현금흐름" 매칭
  - 자산총계 / 부채총계 / 자본총계
  - 매출채권: "매출채권"
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.collectors.dart_fetcher import DartFetcher
from src.utils.logger import get_logger

log = get_logger("dart_fin")


@dataclass
class AnnualSnapshot:
    year: int
    revenue: float = 0.0
    op_profit: float = 0.0
    net_income: float = 0.0
    operating_cf: float = 0.0
    total_assets: float = 0.0
    total_liab: float = 0.0
    total_equity: float = 0.0
    receivables: float = 0.0

    @property
    def opm(self) -> float:
        return (self.op_profit / self.revenue * 100) if self.revenue else 0.0


def _to_float(s: str | None) -> float:
    if not s:
        return 0.0
    s = s.replace(",", "").strip()
    if s in ("", "-", "N/A"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _find_account(items: list[dict], keywords: Iterable[str], sj_div: str | None = None) -> float:
    """account_nm 에 keywords 모두 포함된 첫 항목의 thstrm_amount 반환.

    sj_div 필터: 'IS' (손익), 'BS' (재무), 'CF' (현금흐름) 등.
    """
    kws = list(keywords)
    for it in items:
        if sj_div and it.get("sj_div") != sj_div:
            continue
        nm = (it.get("account_nm") or "").replace(" ", "")
        if all(k.replace(" ", "") in nm for k in kws):
            return _to_float(it.get("thstrm_amount"))
    return 0.0


def parse_annual_payload(items: list[dict], year: int) -> AnnualSnapshot:
    """fnlttSinglAcntAll.json 응답의 list 항목 → AnnualSnapshot."""
    snap = AnnualSnapshot(year=year)
    snap.revenue = (
        _find_account(items, ["매출액"], sj_div="IS")
        or _find_account(items, ["영업수익"], sj_div="IS")
        or _find_account(items, ["수익", "매출"], sj_div="IS")
    )
    snap.op_profit = _find_account(items, ["영업이익"], sj_div="IS")
    snap.net_income = (
        _find_account(items, ["당기순이익"], sj_div="IS")
        or _find_account(items, ["분기순이익"], sj_div="IS")
    )
    snap.operating_cf = (
        _find_account(items, ["영업활동", "현금흐름"], sj_div="CF")
        or _find_account(items, ["영업활동", "순현금"], sj_div="CF")
    )
    snap.total_assets = _find_account(items, ["자산총계"], sj_div="BS")
    snap.total_liab = _find_account(items, ["부채총계"], sj_div="BS")
    snap.total_equity = _find_account(items, ["자본총계"], sj_div="BS")
    snap.receivables = _find_account(items, ["매출채권"], sj_div="BS")
    return snap


def get_annual_snapshot(
    fetcher: DartFetcher, corp_code: str, year: int
) -> AnnualSnapshot | None:
    """연간 사업보고서(11011) 한 해."""
    try:
        items = fetcher.fetch_quarterly_financials(corp_code, str(year), reprt_code="11011")
    except Exception as e:
        log.info(f"financials fetch 실패 corp={corp_code} year={year}: {e}")
        return None
    if not items:
        return None
    return parse_annual_payload(items, year)


def get_recent_annuals(
    fetcher: DartFetcher, corp_code: str, *, years: int = 2, end_year: int | None = None
) -> list[AnnualSnapshot]:
    """최근 N년 연간 스냅샷 (오래된 순)."""
    from src.utils.kst_time import today_kst
    if end_year is None:
        # 사업보고서는 보통 N+1 년 3월 공시. 5월 기준이면 N-1년 사업보고서가 최신.
        end_year = today_kst().year - 1
    out: list[AnnualSnapshot] = []
    for y in range(end_year - years + 1, end_year + 1):
        snap = get_annual_snapshot(fetcher, corp_code, y)
        if snap and snap.revenue > 0:
            out.append(snap)
    return out


def extract_nps_holding_change(major_holdings: list[dict]) -> tuple[float | None, float | None]:
    """
    DART majorstock.json 의 list → (prev_pct, curr_pct).
    국민연금공단 보고건만 필터, 가장 최근 2건의 stkrt(보유비율) 비교.
    """
    nps_records = [
        r for r in major_holdings
        if "국민연금" in (r.get("repror") or "") or "국민연금" in (r.get("ryp") or "")
    ]
    if not nps_records:
        return (None, None)
    # rcept_dt (접수일) 내림차순.
    nps_records.sort(key=lambda r: (r.get("rcept_dt") or ""), reverse=True)
    curr = _to_float(nps_records[0].get("stkrt"))
    prev = _to_float(nps_records[1].get("stkrt")) if len(nps_records) > 1 else None
    return (prev if prev else None, curr if curr else None)
