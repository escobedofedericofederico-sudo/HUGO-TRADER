""""HUGO-TRADER: research backtester. Simulation only; never places real orders."""
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
    pnl: float = 0.0
    reason: str = "signal"


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
    rolling = 0.0
    for i, value in enumerate(values):
        rolling += value
        if i >= period:
            rolling -= values[i - period]
        result.append(rolling / period if i + 1 >= period else None)
    return result


def _drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak > 0:
            worst = min(worst, (value / peak - 1.0) * 100.0)
    return worst


def backtest(
    bars: Iterable[Bar],
    fast: int = 5,
    slow: int = 20,
    initial_cash: float = 10_000.0,
    fee_rate: float = 0.001,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    risk_per_trade: float = 1.0,
) -> dict:
    """Long-only SMA crossover simulation with close-based risk exits.

    A signal formed on bar i is executed on bar i+1 close, avoiding same-bar
    look-ahead. Stop/take levels are checked against closing prices only;
    intraday gaps and slippage are not modelled.
    """
    data = list(bars)
    if fast < 1 or slow < 2 or fast >= slow:
        raise ValueError("Require 1 <= fast < slow")
    if initial_cash <= 0 or not 0 <= fee_rate < 1:
        raise ValueError("Invalid initial cash or fee rate")
    if stop_loss is not None and not 0 < stop_loss < 1:
        raise ValueError("stop_loss must be between 0 and 1 (e.g. 0.05)")
    if take_profit is not None and take_profit <= 0:
        raise ValueError("take_profit must be greater than 0 (e.g. 0.10)")
    if not 0 < risk_per_trade <= 1:
        raise ValueError("risk_per_trade must be in (0, 1]")
    if len(data) < slow + 1:
        raise ValueError(f"Need at least {slow + 1} price rows")
    if any(bar.close <= 0 for bar in data):
        raise ValueError("All close prices must be positive")

    closes = [bar.close for bar in data]
    fast_ma, slow_ma = moving_average(closes, fast), moving_average(closes, slow)
    cash, units = initial_cash, 0.0
    entry_price = 0.0
    entry_cost = 0.0
    trades: list[Trade] = []
    equity_curve: list[float] = []

    for i, bar in enumerate(data):
        # Existing position risk exits take priority, using today's close.
        if units > 0:
            change = bar.close / entry_price - 1.0
            reason = None
            if stop_loss is not None and change <= -stop_loss:
                reason = "stop_loss"
            elif take_profit is not None and change >= take_profit:
                reason = "take_profit"
            elif i > 0 and fast_ma[i - 1] is not None and slow_ma[i - 1] is not None:
                if fast_ma[i - 1] < slow_ma[i - 1]:
                    reason = "signal"
            if reason:
                proceeds = units * bar.close * (1 - fee_rate)
                pnl = proceeds - entry_cost
                cash += proceeds
                trades.append(Trade(bar.date, "SELL", bar.close, cash, pnl, reason))
                units, entry_price, entry_cost = 0.0, 0.0, 0.0

        # Today's signal uses only yesterday's completed bar; execute at today's close.
        if units == 0 and i > 0:
            j = i - 1
            if (fast_ma[j] is not None and slow_ma[j] is not None
                    and fast_ma[j] > slow_ma[j]):
                # risk_per_trade is the fraction of equity allowed to be lost
                # at the stop. Convert that risk budget into position notional.
                allocation = cash * risk_per_trade
                if stop_loss is not None:
                    allocation = min(cash, cash * risk_per_trade / stop_loss)
                units = allocation / (bar.close * (1 + fee_rate))
                entry_cost = units * bar.close * (1 + fee_rate)
                cash -= entry_cost
                entry_price = bar.close
                trades.append(Trade(bar.date, "BUY", bar.close, cash, 0.0, "signal"))

        equity_curve.append(cash + units * bar.close)

    final_value = cash + units * closes[-1]
    closed = [t for t in trades if t.action == "SELL"]
    wins = [t.pnl for t in closed if t.pnl > 0]
    losses = [-t.pnl for t in closed if t.pnl < 0]
    gross_profit, gross_loss = sum(wins), sum(losses)
    buy_hold = initial_cash * closes[-1] / closes[0]
    return {
        "initial_cash": initial_cash,
        "final_value": final_value,
        "return_pct": (final_value / initial_cash - 1) * 100,
        "open_units": units,
        "trades": trades,
        "closed_trades": len(closed),
        "win_rate_pct": (len(wins) / len(closed) * 100) if closed else 0.0,
        "profit_factor": (gross_profit / gross_loss if gross_loss else
                          (float("inf") if gross_profit else 0.0)),
        "max_drawdown_pct": _drawdown(equity_curve),
        "buy_hold_return_pct": (buy_hold / initial_cash - 1) * 100,
        "equity_curve": equity_curve,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HUGO-TRADER paper backtest")
    parser.add_argument("csv", help="CSV file with date,close columns")
    parser.add_argument("--fast", type=int, default=5)
    parser.add_argument("--slow", type=int, default=20)
    parser.add_argument("--cash", type=float, default=10_000)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--stop-loss", type=float, default=None,
                        help="Stop loss fraction, e.g. 0.05 for 5%%")
    parser.add_argument("--take-profit", type=float, default=None,
                        help="Take profit fraction, e.g. 0.10 for 10%%")
    parser.add_argument("--risk", type=float, default=1.0,
                        help="Maximum fraction of cash allocated per trade (0-1)")
    parser.add_argument("--memory-db", default="hugo_memory.sqlite3",
                        help="SQLite file for persistent experience memory")
    parser.add_argument("--no-memory", action="store_true",
                        help="Do not save this backtest to experience memory")
    parser.add_argument("--compare", action="store_true",
                        help="Compare common SMA pairs: 3/10, 5/20, 10/50")
    args = parser.parse_args()
    bars = load_bars(args.csv)
    pairs = [(3, 10), (5, 20), (10, 50)] if args.compare else [(args.fast, args.slow)]
    print("HUGO-TRADER — PAPER BACKTEST (no real orders)")
    for fast, slow in pairs:
        if len(bars) < slow + 1:
            print(f"SMA {fast}/{slow}: skipped (need at least {slow + 1} rows)")
            continue
        result = backtest(bars, fast, slow, args.cash, args.fee,
                          args.stop_loss, args.take_profit, args.risk)
        pf = "∞" if result["profit_factor"] == float("inf") else f"{result['profit_factor']:.2f}"
        print(f"\nSMA {fast}/{slow}")
        print(f"Initial/final: {result['initial_cash']:.2f} / {result['final_value']:.2f}")
        print(f"Strategy return: {result['return_pct']:.2f}% | Buy & hold: {result['buy_hold_return_pct']:.2f}%")
        print(f"Max drawdown: {result['max_drawdown_pct']:.2f}% | Win rate: {result['win_rate_pct']:.2f}%")
        print(f"Profit factor: {pf} | Closed trades: {result['closed_trades']}")
        if not args.no_memory:
            from experience import record_backtest, learning_report
            saved = record_backtest(result["trades"], f"SMA {fast}/{slow}", result, args.memory_db)
            memory = learning_report(args.memory_db)
            print(f"Memoria: {saved['new_trades_saved']} nuevas operaciones guardadas; "
                  f"{memory['total_trades']} experiencias acumuladas; "
                  f"{memory['losses']} pérdidas detectadas.")
        for trade in result["trades"]:
            suffix = f" | PnL {trade.pnl:.2f} | {trade.reason}" if trade.action == "SELL" else ""
            print(f"{trade.date} {trade.action} @ {trade.price:.4f}{suffix}")


if __name__ == "__main__":
    main()
