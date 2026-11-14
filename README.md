# HUGO-TRADER

Educational quantitative-research project. **Paper backtesting only**: no broker connection, API keys, or real order execution.

## Features

- Long-only simple moving-average crossover backtester.
- Stop-loss, take-profit, position sizing, fees and drawdown.
- Comparison with buy-and-hold and alternative SMA pairs.
- **Persistent experience memory** in a local SQLite database.
- Every closed simulated trade is classified as WIN, LOSS or BREAKEVEN.
- Stores entry/exit, P&L, exit reason and a written lesson for each result.
- Detects repeated loss patterns once there are at least five observations in a category.
- Keeps experiment results to compare strategies over time.
- Automated tests in GitHub Actions.

## Requirements

Python 3.10+; no third-party packages.

## Historical data

Create a local `prices.csv` (CSV files are ignored by Git):

```csv
date,close
2026-01-01,100.00
2026-01-02,101.50
2026-01-03,99.80
```

Use at least `slow + 1` rows, in chronological order.

## Run a backtest

```bash
python bot.py prices.csv --fast 5 --slow 20 --cash 10000 --fee 0.001
```

### Risk controls

```bash
python bot.py prices.csv --stop-loss 0.05 --take-profit 0.10 --risk 0.01
```

- `--stop-loss 0.05`: close after a 5% adverse close-to-entry move.
- `--take-profit 0.10`: close after a 10% favourable close-to-entry move.
- `--risk 0.01`: risk budget used to size a position when a stop is supplied; without a stop it caps the cash allocation at 1%.
- `--fee 0.001`: 0.1% fee per simulated transaction.

Stop checks use closing prices, not intraday highs/lows. Gaps, spread, slippage, taxes, dividends and partial fills are not modelled.

## Memory and learning from mistakes

By default each run stores closed simulated trades in `hugo_memory.sqlite3` in the current folder. The database persists between runs and is intentionally excluded from Git.

```bash
# Read the accumulated memory and lessons
python experience.py

# Choose another local database
python bot.py prices.csv --memory-db data/hugo_memory.sqlite3

# Run without saving this experiment
python bot.py prices.csv --no-memory
```

The memory labels outcomes by net P&L after simulated fees:
- **LOSS**: negative realized P&L; records the exit reason and a review lesson.
- **WIN**: positive realized P&L; records what happened without assuming it will repeat.
- **BREAKEVEN**: approximately zero realized P&L.

It summarizes win/loss counts, average and net P&L, worst trades, strategy history and repeated exit-reason patterns. A warning is shown only after at least five observations and a loss rate of 60% or more in that category.

**Important distinction:** this is experience logging and statistical feedback, not a trained neural network. It does not automatically alter strategy parameters or place orders. It avoids claiming a pattern from one loss. The next research step is a walk-forward experiment runner with out-of-sample validation before any candidate strategy can be promoted.

## Compare strategies

```bash
python bot.py prices.csv --compare
```

Compares SMA 3/10, 5/20 and 10/50 where enough rows exist.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Safety

This is an educational simulator, not investment advice or a promise of returns. Backtests do not guarantee future performance. Never commit API keys, passwords or broker credentials. Live trading is not implemented.
