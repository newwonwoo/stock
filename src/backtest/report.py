"""백테스트 결과 → markdown + JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.backtest.historical_runner import BacktestResult


def _md_header(r: BacktestResult) -> str:
    cfg = r.config
    m = r.metrics
    return f"""# 백테스트 결과

## 설정
- 기간: ~{cfg.lookback_years}년 (종료일: {cfg.end_date.isoformat()})
- 초기 자금: {int(cfg.initial_cash):,}원
- universe top: {cfg.universe_top_n}, max_holdings: {cfg.max_holdings}
- 수수료/슬리피지: {cfg.fee_bps} bps / {cfg.slippage_bps} bps

## 성과
| 지표 | 값 |
|---|---|
| 총 수익률 | {m['total_return_pct']}% |
| 연환산 (CAGR) | {m['cagr_pct']}% |
| Sharpe | {m['sharpe']} |
| MDD | {m['mdd_pct']}% |
| 거래 수 | {m['trade_count']} |
| 승률 | {m['win_rate_pct']}% |
| 평균 거래 수익 | {m['avg_trade_pct']}% |
| 알파 (KOSPI 대비) | {m.get('alpha_vs_benchmark_pct')}%pt |
| 벤치마크 (KOSPI) 동기간 | {r.benchmark_total_return_pct}% |
"""


def _md_picks(r: BacktestResult, limit: int = 12) -> str:
    rows = ["## 월별 선정 종목 (최근 12개월)", "", "| 일자 | 종목 | 점수 |", "|---|---|---|"]
    for entry in r.monthly_picks[-limit:]:
        codes = ", ".join(entry["picks"])
        scores = ", ".join(str(s) for s in entry["scores"])
        rows.append(f"| {entry['date']} | {codes} | {scores} |")
    return "\n".join(rows)


def write(out_dir: Path, r: BacktestResult, name: str = "backtest") -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{name}.md"
    json_path = out_dir / f"{name}.json"

    md = "\n\n".join([_md_header(r), _md_picks(r)])
    md_path.write_text(md + "\n", encoding="utf-8")

    payload = {
        "config": {
            "end_date": r.config.end_date.isoformat(),
            "lookback_years": r.config.lookback_years,
            "initial_cash": r.config.initial_cash,
            "universe_top_n": r.config.universe_top_n,
            "max_holdings": r.config.max_holdings,
            "fee_bps": r.config.fee_bps,
            "slippage_bps": r.config.slippage_bps,
        },
        "metrics": r.metrics,
        "benchmark_total_return_pct": r.benchmark_total_return_pct,
        "trades": [
            {
                "code": t.code,
                "entry_date": t.entry_date.isoformat(),
                "exit_date": t.exit_date.isoformat(),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "quantity": t.quantity,
                "return_pct": t.return_pct,
                "days_held": t.days_held,
            }
            for t in r.portfolio.trades
        ],
        "equity_curve": [(d.isoformat(), v) for d, v in r.portfolio.equity_curve],
        "monthly_picks": r.monthly_picks,
    }
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    return md_path, json_path
