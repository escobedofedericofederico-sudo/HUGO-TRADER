# HUGO-TRADER

Educational quantitative-research project. The Python engine is **paper-backtesting only**. The optional MQL4 EA is source-only, demo/tester-gated and disabled by default; no broker connection or demo execution has been verified. The EA is not intended to execute real-account orders.

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

The `--risk` argument has two modes: with `--stop-loss`, it is the fraction of
equity budgeted to lose if the stop is reached (position notional is sized from
that budget); without a stop, it only caps the cash allocation and does not cap
the loss on a price gap.

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

### MetaTrader 4 integration status

The repository now includes an initial MQL4 source file at
`MQL4/Experts/HUGO_TRADER_DemoOnly.mq4`. It is a long-only SMA crossover EA
with one market position per symbol/magic number, a mandatory stop-loss, a maximum
configured risk of 1% of current equity, spread and margin checks, and position sizing
that rounds down (it refuses to force the broker minimum lot when that would
exceed the risk budget). The risk estimate also reserves the configured slippage
on entry and stop execution, and can include an estimated round-turn commission.

**Fail-closed safeguards in the EA:**
- `EnableDemoTrading` defaults to `false`; no order is sent until explicitly enabled.
- Position sizing uses current equity, includes spread plus a two-sided slippage reserve,
  and adds `EstimatedRoundTurnCommissionPerLot` when configured. Set that input to the
  broker's estimated entry-plus-exit commission per lot in the account currency; the
  default `0.0` means commission is not included in the risk estimate.
- Lot precision is derived from the broker's lot step, including fractional steps such
  as `0.25`; the EA rounds down and refuses a size below the broker minimum.
- A same-symbol/same-magic BUY or SELL market position blocks a new entry.
- `MagicNumber` must be positive; zero is rejected because MT4 manual orders commonly use magic 0. Assign a dedicated positive value not shared with another EA.
- Initialization rejects accounts that are neither demo nor Strategy Tester.
- In a live terminal, order paths require `IsConnected()` before cached quotes are refreshed or used; Strategy Tester is exempt because it uses simulated quotes.
- `OnTick`, `OrderSend`, and `OrderClose` each check the demo/tester gate and
  the explicit enable switch.
- After a successful entry, the EA re-selects the broker's order and verifies that
  a stop-loss is present, is below the BUY open price, and is not farther away than
  the configured stop plus the slippage reserve. If that check fails, it attempts
  an immediate demo-only close and prints a critical warning if the close fails.
  This is a best-effort emergency response, not a guarantee against broker, network,
  or market failure; the terminal must be checked if the critical warning appears.
- On every tick, before the new-candle strategy gate, the EA rechecks each matching open
  BUY. A missing/invalid stop or a stop at/above current Bid triggers a demo-only
  emergency-close attempt; failure is logged as critical and requires manual terminal
  inspection. This remains best-effort and cannot guarantee execution during outages.
- Strategy Tester is allowed because its trades are simulated; outside the tester,
  only an account for which MT4 reports `IsDemo()` is accepted.
- No credentials, API keys, or broker passwords are used or stored.

**Important verification limit:** the MQL4 file is source code only. It has not
been compiled in MetaEditor, run in Strategy Tester, or connected to a demo
account from this environment. The Python tests include source-level safety
regression checks, but those checks are not a substitute for an MQL4 compiler
or a platform test. No demo order has been placed or verified.

### Compile and test the EA safely

1. In MT4, open **File → Open Data Folder**.
2. Copy `MQL4/Experts/HUGO_TRADER_DemoOnly.mq4` into the terminal's
   `MQL4/Experts` folder.
3. Open MetaEditor, open the file, and compile it. Resolve any compiler errors
   before proceeding; no compiled `.ex4` file is included in this repository.
4. Run Strategy Tester on historical data first. Set `EnableDemoTrading=true`
   only for the tester run; tester orders are simulated.
5. For a terminal demo test, log in to a **demo account only**, attach the EA,
   and explicitly set `EnableDemoTrading=true`. If MT4 reports a real account,
   initialization is rejected and order functions remain blocked.

Do not attach this EA to a real account or use real funds. Stop-loss sizing is
an estimate: gaps, slippage, tick-value changes, broker execution rules and
market outages can make actual losses exceed the configured risk. This EA is
an educational prototype, not investment advice or a proven profitable system.


## Walk-forward research lab (out-of-sample)

The research lab selects an SMA pair on a historical training window, then evaluates
that selected pair on the next unseen test window. It repeats this process through
the available history. Candidate selection never reads the corresponding test window.

```bash
python research_lab.py prices.csv --train 120 --test 30 --step 30
```

- `--train`: number of historical rows used to select a candidate.
- `--test`: number of subsequent unseen rows used for evaluation.
- `--step`: distance between test-window starts (defaults to test size).
- Each test fold starts as a fresh simulation; indicator warm-up occurs inside that
  test window, so no training trades or equity are carried into the test result.
- At the final test close, any open SMA position is liquidated and charged the same
  exit fee as the buy-and-hold benchmark. The reported SMA return and drawdown include
  this terminal fee, avoiding a favorable mark-to-market comparison.
- Reports each fold's selected SMA pair, training return, unseen test return and
  test drawdown.
- Adds robustness diagnostics across unseen windows: median return, return variability,
  longest consecutive losing streak, and the share of windows that beat buy-and-hold.
  These describe consistency; they do not predict future returns.
- A strategy is only labelled **candidate for more validation** after at least
  three test folds, positive average test return, at least 60% positive folds and
  no test-fold drawdown worse than 30%.

This gate is deliberately conservative but is not proof of an edge. The lab does
not model intraday execution, spread, slippage, taxes, dividends or survivorship
bias, and short test windows can be noisy. Do not use the label as permission for
live trading. More data and independent validation are required.


## Simular con $20.000 ARS en walk-forward

El laboratorio calcula el efecto de encadenar los rendimientos de cada ventana fuera de muestra sobre un capital inicial de referencia:

```bash
python research_lab.py prices.csv --train 120 --test 30 --step 30 --capital-ars 20000 --fee 0.001
```

El informe muestra capital inicial, capital final, ganancia/pérdida neta en ARS y el detalle por ventana, con capital compuesto. La comisión configurada por defecto en el workflow es 0,1% por operación simulada.

**Limitación cambiaria:** los precios usados son BTC-USD. La conversión a pesos es una simulación proporcional que mantiene constante el tipo de cambio ARS/USD; no incorpora variación del dólar, spread cambiario, impuestos ni comisiones de un exchange argentino. Por eso el resultado en ARS es ilustrativo, no una cotización ejecutable ni una promesa de rendimiento. Los folds se simulan de forma independiente y sus rendimientos se encadenan para estimar el efecto compuesto; no es una cuenta conectada a un broker.


## Comparación con comprar y mantener y revisión de pérdidas

Cada ventana fuera de muestra compara la estrategia SMA seleccionada con comprar BTC al primer cierre y vender al último cierre de esa misma ventana. El benchmark cobra comisión simulada tanto al entrar como al salir. El informe encadena por separado el capital de la estrategia y el benchmark, muestra en cuántas ventanas la estrategia supera a BTC y resume patrones para revisar en las ventanas perdedoras. Estas lecciones son diagnósticos descriptivos: no modifican parámetros automáticamente ni usan información futura para seleccionar la estrategia.


## Motor de diagnóstico y aprendizaje controlado

El motor nuevo lee la memoria SQLite y calcula expectativa, tasa de acierto, promedio de ganancia/pérdida, factor de beneficio y resultados por estrategia y motivo de salida. Si se proporciona el CSV histórico, atribuye cada operación al régimen conocido ANTES de su entrada; nunca usa el precio de entrada ni datos posteriores para etiquetar el contexto.

```bash
python learning_engine.py
python learning_engine.py --prices prices.csv
python learning_engine.py --prices prices.csv --min-samples 10 --json
```

El motor entrega diagnósticos y propuestas de revisión, pero no cambia parámetros ni ejecuta órdenes. Las muestras de backtests que se solapan pueden estar correlacionadas; el tamaño de la memoria no equivale al mismo número de experimentos independientes. Una estadística favorable no autoriza operar con dinero real.


## Laboratorio de experimentos controlados

`experiment_lab.py` compara configuraciones predefinidas de SMA, stop-loss y tamaño de posición mediante ventanas walk-forward. En cada ventana elige la configuración exclusivamente con el bloque de entrenamiento y la evalúa en el bloque posterior no visto. No modifica la configuración principal, no guarda operaciones en la memoria, no despliega estrategias y no ejecuta órdenes.

```bash
python experiment_lab.py prices.csv
python experiment_lab.py prices.csv --train 180 --test 60 --step 60 --cash 10000 --fee 0.001
python experiment_lab.py prices.csv --json
```

La salida es investigación, no recomendación de inversión. Las ventanas pueden solaparse y no son experimentos estadísticamente independientes. Toda configuración elegida requiere validación adicional antes de cualquier uso fuera de simulación.
