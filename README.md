# HUGO-TRADER

Educational trading research project. The current version is a **historical backtester only**: it does not connect to a broker, request API credentials, or place real orders.

## What it does

- Reads historical closing prices from a CSV file.
- Calculates fast and slow simple moving averages.
- Simulates long-only entries and exits.
- Includes a configurable fee rate and starting cash.
- Prints final simulated portfolio value, return, and trades.

This is a learning tool, not investment advice or a promise of returns. Backtests are simplified and do not guarantee future results. The current simulator assumes execution at the same bar close used to calculate the signal, which can make results optimistic.

## Requirements

- Python 3.10 or newer
- No third-party packages required

## CSV format

Create a local file named `prices.csv` (CSV files are ignored by Git):

```csv
date,close
2026-01-01,100.00
2026-01-02,101.50
2026-01-03,99.80
```

Use at least 20 rows with the default settings.

## Run a backtest

```bash
python bot.py prices.csv
```

Optional parameters:

```bash
python bot.py prices.csv --fast 5 --slow 20 --cash 10000 --fee 0.001
```

- `--fast`: fast moving-average period (default: 5)
- `--slow`: slow moving-average period (default: 20)
- `--cash`: initial simulated cash (default: 10000)
- `--fee`: fee per transaction as a decimal (default: 0.001 = 0.1%)

## Run tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the unit tests on pushes and pull requests to `main`.

## Safety

Do not add broker keys, passwords, or `.env` files to the repository. Live trading is intentionally not implemented.