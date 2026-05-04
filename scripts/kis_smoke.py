"""
KIS fetcher smoke test.

KIS_APP_KEY / KIS_APP_SECRET 환경변수 필요. (TradeBot 과 동일 키)

확인:
  1. 토큰 발급 + 캐시 저장
  2. 시장 지수 (KOSPI/KOSDAQ/KOSPI200)
  3. 삼성전자 일봉 30개
"""

from __future__ import annotations

import sys

from src.collectors.kis_fetcher import KisFetcher


def main() -> int:
    f = KisFetcher()

    print("[1] 시장 지수 ...")
    idx = f.fetch_market_indices()
    for name, payload in idx.items():
        cur = payload.get("bstp_nmix_prpr") or payload.get("bstp_nmix_prdy_clpr") or "?"
        print(f"  {name}: {cur}")

    print("[2] 005930 일봉 ...")
    ohlcv = f.fetch_daily_ohlcv("005930", count=30)
    print(f"  rows={len(ohlcv)}")

    print("[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
