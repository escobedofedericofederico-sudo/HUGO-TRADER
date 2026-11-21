# HUGO-TRADER MQL4 EA

## Estado

`Experts/HUGO_TRADER_DemoOnly.mq4` is an educational, long-only SMA crossover Expert Advisor. It is source code only. The repository does not contain a compiled `.ex4`, and no MetaEditor compilation, Strategy Tester run, or broker demo execution has been verified by GitHub Actions.

The EA is deliberately disabled by default:

- `EnableDemoTrading=false` on a fresh attach.
- `OnInit`, `OnTick`, and every order-opening/closing function reject environments that are neither MT4 demo nor Strategy Tester.
- Strategy Tester is allowed because its orders are simulated.
- No broker credentials, passwords, API keys, or tokens are read or stored.

Do not attach it to a real account. Do not change the guards to make a real account pass.

## Entry and risk controls

- One BUY position maximum per symbol and magic number. A BUY or SELL market order with the same symbol/magic blocks another entry.
- `MagicNumber` must be a positive integer. Zero is rejected because MT4 manual orders commonly use magic 0; use a dedicated positive value that is not shared with another EA.
- The position check is repeated inside the entry function immediately before sizing and sending the order.
- Risk percentage is limited to 1% of current account equity.
- Stop-loss is mandatory. Take-profit may be disabled with zero.
- Lot size is rounded down to the broker lot step. The EA never rounds up to the minimum lot when that would exceed the estimated risk budget.
- The maximum lot is capped and then rounded down to the lot step.
- The estimate reserves the spread and configured slippage for entry and stop execution. Set `EstimatedRoundTurnCommissionPerLot` to the broker's estimated entry-plus-exit commission per lot, in account currency. The default is zero, so commission is not included unless configured.
- Spread, broker stop-level, and free-margin checks must pass.
- Quotes, point size, symbol tick values, equity, calculated risk, and free-margin results must be finite and positive where required. Crossed or unavailable quotes block order operations.
- After entry, the EA re-selects the order and checks that a protective stop exists below the BUY open price and is not farther away than the configured stop plus the slippage reserve. If not, it attempts a demo-only emergency close and logs a critical warning if the close fails.
- On every tick, before the new-bar strategy gate, it rechecks each matching open BUY. A missing/invalid stop or a stop at/above current Bid triggers a demo-only emergency-close attempt. A failed close is logged as critical and requires manual terminal inspection.
- The protection check also runs when `EnableDemoTrading=false`. In that safe mode it is read-only: it warns if protection is invalid or cannot be verified, but it never sends an emergency close or a new entry.
- This emergency close is best effort. Broker rejection, connection loss, market gaps, or execution outages can prevent a close.

These checks reduce known risks; they do not guarantee that actual loss cannot exceed the estimate. Tick value, spread, slippage, commission, and broker execution rules can change.

## Local validation

1. In MT4, choose **File → Open Data Folder**.
2. Copy `Experts/HUGO_TRADER_DemoOnly.mq4` into the terminal's `MQL4/Experts` folder.
3. Open MetaEditor and compile the file. Resolve every compiler error before continuing. The repository does not supply a compiled `.ex4`.
4. Run Strategy Tester on historical data. Inspect the Journal and Experts tabs, confirm the EA is identified as the demo-only build, and verify that stop-losses are present on every opened BUY.
5. Only after the tester checks, attach it to an MT4 demo account and set `EnableDemoTrading=true`. Confirm the terminal is logged into a demo account before enabling AutoTrading.
6. If any critical stop/close warning appears, stop the test and inspect the order manually. Do not move to real funds.

The Python CI test `tests/test_mql4_safety.py` checks selected source-code safeguards. It is a static regression check, not an MQL4 compiler, broker simulator, or proof of execution behavior.
