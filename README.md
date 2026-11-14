# HUGO-TRADER

Educational quantitative-research project. **Paper backtesting only**: no broker connection, API keys, or real order execution.

## Features

- Simple moving-average crossover strategy (long-only).
- Stop-loss and take-profit exits, checked against closing prices.
- Position sizing from a configurable risk budget when a stop-loss is set.
- Transaction fees, trade-by-trade realized P&L, win rate, profit factor.
- Maximum drawdown and buy-and-hold benchmark comparison.
- Compare several SMA pairs with one command.
- Automated unit tests on pushes and pull requests to `main`.

## Requirements

- Python 3.10+
- No third-party packages

## Historical data

Create a local `prices.csv` (CSV files are ignored by Git):

```csv
date,close
2026-01-01,100.00
2026-01-02,101.50
2026-01-03,99.80
```

Use at least `slow + 1` rows. Dates are labels; rows must be in chronological order.

## Run a basic backtest

```bash
python bot.py prices.csv
```

## Risk controls

```bash
python bot.py prices.csv --fast 5 --slow 20 --cash 10000 --fee 0.001 --stop-loss 0.05 --take-profit 0.10 --risk 0.01
```

- `--stop-loss 0.05`: exit after a 5% loss from entry, based on closing prices.
- `--take-profit 0.10`: exit after a 10% gain from entry, based on closing prices.
- `--risk 0.01`: risk budget of 1% of current cash/equity. When a stop is set, position notional is sized from the stop distance and capped at available cash. Without a stop, it limits the fraction of cash deployed.
- `--fee 0.001`: 0.1% fee on each simulated transaction.

Risk exits use closing prices, not intraday high/low. Stop execution can be worse than the stop threshold after a gap. Slippage, spread, taxes, dividends, shorting and partial fills are not modelled.

## Compare strategies

```bash
python bot.py prices.csv --compare --cash 10000 --fee 0.001
```

Compares SMA 3/10, 5/20 and 10/50 where enough data exists. Compare results on out-of-sample periods; do not choose parameters solely because they fit past prices.

## Metrics

- Strategy return and buy-and-hold return
- Maximum peak-to-trough drawdown
- Win rate of closed trades
- Profit factor (gross winning P&L / gross losing P&L)
- Closed trades and each entry/exit reason

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs this suite automatically.

## Important limitations

This is a simplified educational simulator, not investment advice or a promise of returns. Signals use a completed previous close and simulated entries occur at the next close to reduce same-bar look-ahead, but real execution can differ materially. Backtests do not guarantee future performance. **Never add broker credentials or enable live trading based on these results.**
