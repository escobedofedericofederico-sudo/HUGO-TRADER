"""Walk-forward research lab for HUGO-TRADER (simulation only).

Each fold selects an SMA pair using only its training window, then evaluates
that selected pair on the immediately following, unseen test window.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from bot import Bar, backtest, load_bars


@dataclass(frozen=True)
class FoldResult:
    fold: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    selected_fast: int
    selected_slow: int
    train_return_pct: float
    test_return_pct: float
    test_drawdown_pct: float
    test_closed_trades: int


DEFAULT_CANDIDATES = ((3, 10), (5, 20), (8, 21), (10, 30), (10, 50))


def _score(result: dict) -> float:
    """Conservative training score: penalize drawdown, never inspect test data."""
    return result["return_pct"] - 0.5 * abs(result["max_drawdown_pct"])


def walk_forward(
    bars: Iterable[Bar],
    candidates: Iterable[tuple[int, int]] = DEFAULT_CANDIDATES,
    train_size: int = 120,
    test_size: int = 30,
    step_size: int | None = None,
    initial_cash: float = 10_000.0,
    fee_rate: float = 0.001,
) -> dict:
    data = list(bars)
    pairs = tuple((int(f), int(s)) for f, s in candidates)
    step = test_size if step_size is None else step_size
    if train_size < 12 or test_size < 3 or step < 1:
        raise ValueError("Use train_size >= 12, test_size >= 3 and step_size >= 1")
    if not pairs or any(f < 1 or s < 2 or f >= s for f, s in pairs):
        raise ValueError("Candidates must contain valid SMA pairs (fast < slow)")
    if any(b.close <= 0 for b in data):
        raise ValueError("All close prices must be positive")

    folds: list[FoldResult] = []
    test_start = train_size
    fold_no = 1
    while test_start + test_size <= len(data):
        train = data[test_start - train_size:test_start]
        test = data[test_start:test_start + test_size]
        eligible = [(f, s) for f, s in pairs if len(train) >= s + 1 and len(test) >= s + 1]
        if not eligible:
            raise ValueError("No candidate fits both the training and test windows; increase --test or reduce slow periods")

        # Select solely on training data. Stable tie-break favours simpler/faster pair.
        ranked = []
        for fast, slow in eligible:
            result = backtest(train, fast=fast, slow=slow,
                              initial_cash=initial_cash, fee_rate=fee_rate)
            ranked.append((_score(result), -slow, -fast, fast, slow, result))
        _, _, _, chosen_fast, chosen_slow, train_result = max(ranked, key=lambda x: x[:3])

        # The test window is a fresh simulation. Its first bars are naturally
        # consumed by indicator warm-up; no training trades or equity leak into it.
        test_result = backtest(test, fast=chosen_fast, slow=chosen_slow,
                               initial_cash=initial_cash, fee_rate=fee_rate)
        folds.append(FoldResult(
            fold=fold_no,
            train_start=train[0].date, train_end=train[-1].date,
            test_start=test[0].date, test_end=test[-1].date,
            selected_fast=chosen_fast, selected_slow=chosen_slow,
            train_return_pct=train_result["return_pct"],
            test_return_pct=test_result["return_pct"],
            test_drawdown_pct=test_result["max_drawdown_pct"],
            test_closed_trades=test_result["closed_trades"],
        ))
        fold_no += 1
        test_start += step

    if not folds:
        raise ValueError("Not enough rows for one complete train + test fold")

    returns = [f.test_return_pct for f in folds]
    positive = sum(value > 0 for value in returns)
    average = sum(returns) / len(returns)
    # Conservative research gate; this is a filter, not proof of future profit.
    promoted = (len(folds) >= 3 and average > 0
                and positive / len(folds) >= 0.60
                and all(f.test_drawdown_pct > -30 for f in folds))
    return {
        "folds": [asdict(fold) for fold in folds],
        "fold_count": len(folds),
        "average_test_return_pct": average,
        "positive_test_folds": positive,
        "positive_fold_rate_pct": positive / len(folds) * 100,
        "worst_test_return_pct": min(returns),
        "promotion_candidate": promoted,
        "decision": ("CANDIDATA PARA MÁS VALIDACIÓN" if promoted
                     else "NO PROMOCIONAR: evidencia insuficiente o resultados débiles"),
        "warning": ("La prueba fuera de muestra reduce el sobreajuste, pero no elimina "
                    "sesgos, gaps, slippage, impuestos ni garantiza resultados futuros."),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HUGO-TRADER walk-forward research lab")
    parser.add_argument("csv", help="CSV histórico con columnas date,close")
    parser.add_argument("--train", type=int, default=120)
    parser.add_argument("--test", type=int, default=30)
    parser.add_argument("--step", type=int, default=None)
    parser.add_argument("--cash", type=float, default=10_000)
    parser.add_argument("--fee", type=float, default=0.001)
    args = parser.parse_args()
    report = walk_forward(load_bars(args.csv), train_size=args.train,
                          test_size=args.test, step_size=args.step,
                          initial_cash=args.cash, fee_rate=args.fee)
    print("HUGO-TRADER — WALK-FORWARD (solo simulación)")
    for fold in report["folds"]:
        print(f"Fold {fold['fold']}: SMA {fold['selected_fast']}/{fold['selected_slow']} | "
              f"train {fold['train_return_pct']:.2f}% | "
              f"TEST {fold['test_return_pct']:.2f}% | "
              f"DD test {fold['test_drawdown_pct']:.2f}%")
    print(f"Promedio fuera de muestra: {report['average_test_return_pct']:.2f}%")
    print(f"Folds positivos: {report['positive_test_folds']}/{report['fold_count']}")
    print(report["decision"])
    print(report["warning"])


if __name__ == "__main__":
    main()
