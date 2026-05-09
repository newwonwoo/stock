"""
DART 재무 응답 → 분석기 입력 변환.

핵심 함수:
  - get_annual_snapshot(fetcher, corp_code, year) → AnnualSnapshot
  - get_recent_annuals(fetcher, corp_code, years=2) → list[AnnualSnapshot]
  - extract_nps_holding_change(records) → NpsChange (prev/curr/dates 포함)

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


@dataclass
class NpsChange:
    """국민연금 보유비중 변화 + 일자 메타.

    prev_pct/curr_pct: stkrt (보유비율, %)
    latest_bsis_de:    가장 최근 보고의 변동 기준일 (YYYYMMDD) — 실제 매수/매도일
    latest_rcept_dt:   가장 최근 보고의 DART 공시 접수일
    first_buy_de:      NPS 가 처음 등장한 보고의 변동 기준일 (신규 편입 시점)
    """
    prev_pct: float | None = None
    curr_pct: float | None = None
    latest_bsis_de: str | None = None
    latest_rcept_dt: str | None = None
    first_buy_de: str | None = None


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


def _fmt_yyyymmdd(s: str | None) -> str | None:
    """DART 의 'YYYYMMDD' → 'YYYY-MM-DD'. 빈 값/이상치는 None."""
    if not s:
        return None
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


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


def extract_nps_holding_change(major_holdings: list[dict]) -> NpsChange:
    """
    DART majorstock.json 의 list → NpsChange.

    국민연금공단 보고건만 필터.
    - 가장 최근 1건: curr_pct + latest_bsis_de (실제 매수/매도일) + latest_rcept_dt (공시일)
    - 가장 오래된 1건: first_buy_de (신규편입 시점)
    - 두 번째 최근 1건: prev_pct (직전 비중)
    """
    nps_records = [
        r for r in major_holdings
        if "국민연금" in (r.get("repror") or "") or "국민연금" in (r.get("ryp") or "")
    ]
    out = NpsChange()
    if not nps_records:
        return out

    # rcept_dt (접수일) 내림차순.
    nps_records.sort(key=lambda r: (r.get("rcept_dt") or ""), reverse=True)
    latest = nps_records[0]
    curr = _to_float(latest.get("stkrt"))
    out.curr_pct = curr if curr else None
    out.latest_bsis_de = _fmt_yyyymmdd(latest.get("bsis_de"))
    out.latest_rcept_dt = _fmt_yyyymmdd(latest.get("rcept_dt"))

    if len(nps_records) > 1:
        prev = _to_float(nps_records[1].get("stkrt"))
        out.prev_pct = prev if prev else None

    # 가장 오래된 보고 = 신규 편입 시작 (첫 보고). bsis_de 우선, 없으면 rcept_dt.
    oldest = nps_records[-1]
    out.first_buy_de = (
        _fmt_yyyymmdd(oldest.get("bsis_de"))
        or _fmt_yyyymmdd(oldest.get("rcept_dt"))
    )

    return out
