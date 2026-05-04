"""
백테스트용 가상 포트폴리오.

특징:
  - 동일가중 진입 (각 진입 종목에 균등 비중)
  - 슬리피지 (slippage_bps) + 수수료 (fee_bps) 가산
  - 매월 rebalance: 기존 포지션 모두 청산 → 신규 N개 균등 진입
  - 일별 equity curve 박제
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass
class Position:
    code: str
    entry_date: date
    entry_price: float
    quantity: int
    invested: float


@dataclass
class Trade:
    code: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    return_pct: float
    days_held: int


@dataclass
class Portfolio:
    initial_cash: float = 100_000_000  # 1억 default
    cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[tuple[date, float]] = field(default_factory=list)
    fee_bps: float = 15.0       # 15 bps = 0.15% (왕복 매수+매도)
    slippage_bps: float = 10.0  # 10 bps

    def __post_init__(self) -> None:
        if self.cash == 0.0:
            self.cash = self.initial_cash

    def _adjusted_price(self, price: float, side: str) -> float:
        slip = price * (self.slippage_bps / 10000)
        return price + slip if side == "BUY" else price - slip

    def market_value(self, prices: dict[str, float]) -> float:
        v = self.cash
        for code, pos in self.positions.items():
            p = prices.get(code, pos.entry_price)
            v += pos.quantity * p
        return v

    def open(self, code: str, on_date: date, price: float, target_amount: float) -> Position | None:
        adj = self._adjusted_price(price, "BUY")
        if adj <= 0:
            return None
        qty = int(target_amount // adj)
        if qty <= 0:
            return None
        cost = qty * adj
        fee = cost * (self.fee_bps / 2 / 10000)  # 매수만 절반
        if cost + fee > self.cash:
            return None
        self.cash -= cost + fee
        pos = Position(code=code, entry_date=on_date, entry_price=adj, quantity=qty, invested=cost + fee)
        self.positions[code] = pos
        return pos

    def close(self, code: str, on_date: date, price: float) -> Trade | None:
        pos = self.positions.pop(code, None)
        if pos is None:
            return None
        adj = self._adjusted_price(price, "SELL")
        proceeds = pos.quantity * adj
        fee = proceeds * (self.fee_bps / 2 / 10000)
        self.cash += proceeds - fee
        pnl = (proceeds - fee) - pos.invested
        days = (on_date - pos.entry_date).days
        ret = pnl / pos.invested if pos.invested else 0.0
        trade = Trade(
            code=code,
            entry_date=pos.entry_date,
            exit_date=on_date,
            entry_price=pos.entry_price,
            exit_price=adj,
            quantity=pos.quantity,
            pnl=pnl,
            return_pct=round(ret * 100, 2),
            days_held=days,
        )
        self.trades.append(trade)
        return trade

    def close_all(self, on_date: date, prices: dict[str, float]) -> list[Trade]:
        out = []
        for code in list(self.positions.keys()):
            p = prices.get(code)
            if p is None:
                continue
            t = self.close(code, on_date, p)
            if t:
                out.append(t)
        return out

    def mark(self, on_date: date, prices: dict[str, float]) -> None:
        self.equity_curve.append((on_date, self.market_value(prices)))

    def summary(self) -> dict[str, Any]:
        last_equity = self.equity_curve[-1][1] if self.equity_curve else self.cash
        return {
            "initial_cash": self.initial_cash,
            "final_equity": round(last_equity, 0),
            "total_return_pct": round((last_equity - self.initial_cash) / self.initial_cash * 100, 2),
            "trades": len(self.trades),
            "open_positions": len(self.positions),
        }
