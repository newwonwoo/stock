"""
DART fetcher smoke test.

DART_API_KEY 환경변수 필요.

확인:
  1. corp_codes 매핑에 삼성전자(005930) / SK하이닉스(000660) 존재
  2. 삼성전자 1Q 재무 API 응답 (status 000 또는 013)
  3. 어제 일별 공시 목록 fetch (>=0건)

운영 키 호출이므로 GitHub Actions / 사용자 PC 에서만 실행.
"""

from __future__ import annotations

import sys
from datetime import timedelta

from src.collectors.dart_fetcher import DartFetcher
from src.utils.kst_time import fmt_compact, today_kst


def main() -> int:
    f = DartFetcher()

    print("[1] fetch_corp_codes ...")
    codes = f.fetch_corp_codes()
    by_stock = {c.stock_code: c for c in codes if c.stock_code}
    samsung = by_stock.get("005930")
    hynix = by_stock.get("000660")
    if not samsung or not hynix:
        print(f"  FAIL: samsung={samsung} hynix={hynix}")
        return 1
    print(f"  OK: 삼성전자 corp_code={samsung.corp_code}, SK하이닉스 corp_code={hynix.corp_code}")

    print("[2] fetch_quarterly_financials (삼성전자, 2025, 1Q) ...")
    fin = f.fetch_quarterly_financials(samsung.corp_code, bsns_year="2025", reprt_code="11013")
    print(f"  rows={len(fin)} (0 도 정상 — 분기 미공시 가능)")

    print("[3] fetch_daily_disclosures (어제) ...")
    yday = today_kst() - timedelta(days=1)
    disc = f.fetch_daily_disclosures(fmt_compact(yday))
    print(f"  count={len(disc)}")

    print(f"[done] DART calls used: {f.call_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
