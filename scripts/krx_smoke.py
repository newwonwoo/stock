"""
KRX fetcher smoke test.

키 없음. pykrx 만 깔려있으면 실행 가능.

확인:
  1. universe 시총 ≥5천억 카운트 (KOSPI+KOSDAQ)
  2. 삼성전자(005930) OHLCV 30일
  3. 어제 short_top10 KOSPI/KOSDAQ
"""

from __future__ import annotations

import sys

from src.collectors.krx_fetcher import (
    fetch_ohlcv,
    fetch_short_top10,
    fetch_universe_by_market_cap,
)


def main() -> int:
    print("[1] universe ≥5천억 ...")
    uni = fetch_universe_by_market_cap()
    print(f"  total={len(uni)}")
    print(f"  sample top3: {[(t.code, t.name, t.market_cap) for t in uni[:3]]}")

    print("[2] 005930 OHLCV 30일 ...")
    df = fetch_ohlcv("005930", days=30)
    print(f"  rows={len(df)} last_close={df['종가'].iloc[-1] if len(df) else 'n/a'}")

    print("[3] short_top10 ...")
    s = fetch_short_top10()
    for mkt, items in s.items():
        print(f"  {mkt}: {[(it['code'], it['name']) for it in items[:3]]}")

    print("[done]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
