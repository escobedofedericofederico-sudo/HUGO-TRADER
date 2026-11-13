"""HUGO-TRADER: educational moving-average backtester (paper trading only).

Input CSV columns: date, close
No broker connection, API keys, or live order execution.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Bar:
    date: str
    close: float


@dataclass(frozen=True)
class Trade:
    date: str
    action: str
    price: float
    cash: float


def load_bars(path: str | Path) -> list[Bar]:
    bars: list[Bar] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"date", "close"}.issubset(
            {name.strip().lower() for name in reader.fieldnames}
        ):
            raise ValueError("CSV must contain 'date' and 'close' columns")
        for row in reader:
            normalized = {k.strip().lower(): v for k, v in row.items() if k}
            try:
                close = float(normalized["close"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"Invalid close price in row: {row}") from exc
            if close <= 0:
                raise ValueError(f"Close price must be positive: {row}")
            bars.append(Bar(str(normalized.get("date", "")), close))
    if not bars:
        raise ValueError("CSV contains no price rows")
    return bars


def moving_average(values: list[float], period: int) -> list[float | None]:
    if period < 1:
        raise ValueError("Moving-average period must be at least 1")
    result: list[float | None] = []
    for i in range(len(values)):
        result.append(
            sum(values[i - period + 1 : i + 1]) / period
            if i + 1 >= period else None
        )
    return result


def backtest(
    bars: Iterable[Bar],
    fast: int = 5,
    slow: int = 20,
    initial_cash: float = 10_000.0,
    fee_rate: float = 0.001,
) -> dict:
    data = list(bars)
    if fast < 1 or slow < 2 or fast >= slow:
        raise ValueError("Require 1 <= fast < slow")
    if initial_cash <= 0 or not 0 <= fee_rate < 1:
        raise ValueError("Invalid initial cash or fee rate")
    if len(data) < slow:
        raise ValueError(f"Need at least {slow} price rows")

    closes = [bar.close for bar in data]
    fast_ma = moving_average(closes, fast)
    slow_ma = moving_average(closes, slow)
    cash, units, trades = initial_cash, 0.0, []

    # Signals are evaluated at each close; orders are simulated at that close.
    for i, bar in enumerate(data):
        if fast_ma[i] is None or slow_ma[i] is None:
            continue
        if units == 0 and fast_ma[i] > slow_ma[i]:
            units = cash / (bar.close * (1 + fee_rate))
            cash -= units * bar.close * (1 + fee_rate)
            trades.append(Trade(bar.date, "BUY", bar.close, cash))
        elif units > 0 and fast_ma[i] < slow_ma[i]:
            cash += units * bar.close * (1 - fee_rate)
            units = 0.0
            trades.append(Trade(bar.date, "SELL", bar.close, cash))

    final_value = cash + units * closes[-1]
    return {
        "initial_cash": initial_cash,
        "final_value": final_value,
        "return_pct": (final_value / initial_cash - 1) * 100,
        "open_units": units,
        "trades": trades,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HUGO-TRADER paper backtest")
    parser.add_argument("csv", help="CSV file with date,close columns")
    parser.add_argument("--fast", type=int, default=5)
    parser.add_argument("--slow", type=int, default=20)
    parser.add_argument("--cash", type=float, default=10_000)
    parser.add_argument("--fee", type=float, default=0.001)
    args = parser.parse_args()

    result = backtest(
        load_bars(args.csv), args.fast, args.slow, args.cash, args.fee
    )
    print("HUGO-TRADER — PAPER BACKTEST (no real orders)")
    print(f"Initial cash: {result['initial_cash']:.2f}")
    print(f"Final value:  {result['final_value']:.2f}")
    print(f"Return:       {result['return_pct']:.2f}%")
    print(f"Trades:       {len(result['trades'])}")
    for trade in result["trades"]:
        print(f"{trade.date} {trade.action} @ {trade.price:.4f}")


if __name__ == "__main__":
    main()
