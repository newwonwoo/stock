"""
백테스트 CLI.

env:
  BACKTEST_LOOKBACK_YEARS   default 5
  BACKTEST_INITIAL_CASH     default 100000000
  BACKTEST_UNIVERSE_TOP_N   default 50
  BACKTEST_MAX_HOLDINGS     default 5
  BACKTEST_END_DATE         default today (YYYY-MM-DD)
"""

from __future__ import annotations

import os
import sys
from datetime import date

from src import config
from src.backtest.historical_runner import BacktestConfig, run
from src.backtest.report import write
from src.utils.kst_time import today_kst
from src.utils.logger import get_logger

log = get_logger("backtest_cli")


def _parse_end_date() -> date:
    s = os.environ.get("BACKTEST_END_DATE", "")
    if s:
        return date.fromisoformat(s)
    return today_kst()


def main() -> int:
    cfg = BacktestConfig(
        end_date=_parse_end_date(),
        lookback_years=int(os.environ.get("BACKTEST_LOOKBACK_YEARS", "5")),
        initial_cash=float(os.environ.get("BACKTEST_INITIAL_CASH", "100000000")),
        universe_top_n=int(os.environ.get("BACKTEST_UNIVERSE_TOP_N", "50")),
        max_holdings=int(os.environ.get("BACKTEST_MAX_HOLDINGS", "5")),
    )
    log.info(f"config: {cfg}")

    result = run(cfg)
    md_path, json_path = write(config.OUT_DIR, result, name=f"backtest_{cfg.end_date.isoformat()}")
    log.info(f"report: {md_path} / {json_path}")
    log.info(f"summary: {result.metrics}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
