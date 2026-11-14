"""HUGO-TRADER experiment lab: train-only selection, unseen paper tests.

It evaluates a small, predeclared set of SMA/risk configurations. Each fold
selects one configuration using training data only, then tests it on the next
unseen block. No live orders, no automatic deployment, no parameter mutation.
"""
from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import asdict, dataclass
from typing import Iterable

from bot import Bar, backtest, load_bars


@dataclass(frozen=True)
class Candidate:
    fast: int
    slow: int
    stop_loss: float | None
    risk_per_trade: float

    @property
    def name(self) -> str:
        stop = "none" if self.stop_loss is None else f"{self.stop_loss:.0%}"
        return f"SMA {self.fast}/{self.slow} | SL {stop} | risk {self.risk_per_trade:.0%}"


def default_candidates() -> tuple[Candidate, ...]:
    return tuple(
        Candidate(fast, slow, stop, risk)
        for fast, slow in ((3, 10), (5, 20), (10, 50))
        for stop in (None, 0.05, 0.10)
        for risk in (0.5, 1.0)
    )


def _score(result: dict) -> float:
    # Training-only score: return penalized by drawdown. No test data involved.
    return float(result["return_pct"]) - 0.5 * abs(float(result["max_drawdown_pct"]))


def _liquidated_return(result: dict, bars: list[Bar], fee: float) -> float:
    final_value = float(result["final_value"])
    units = float(result["open_units"])
    final_value -= units * bars[-1].close * fee
    return (final_value / float(result["initial_cash"]) - 1.0) * 100.0


def run_experiments(
    bars: Iterable[Bar],
    candidates: Iterable[Candidate] | None = None,
    train_size: int = 180,
    test_size: int = 60,
    step_size: int | None = None,
    initial_cash: float = 10_000.0,
    fee_rate: float = 0.001,
    min_trades: int = 2,
) -> dict:
    data = list(bars)
    configs = tuple(default_candidates() if candidates is None else candidates)
    step = test_size if step_size is None else step_size
    if not data or not configs:
        raise ValueError("Se necesitan precios y candidatos")
    if train_size < 12 or test_size < 3 or step < 1:
        raise ValueError("Usá train >= 12, test >= 3 y step >= 1")
    if initial_cash <= 0 or not 0 <= fee_rate < 1 or min_trades < 0:
        raise ValueError("Parámetros de capital, comisión o min_trades inválidos")
    if any(c.fast < 1 or c.slow <= c.fast for c in configs):
        raise ValueError("Cada candidato requiere 1 <= fast < slow")
    if any(c.stop_loss is not None and not 0 < c.stop_loss < 1 for c in configs):
        raise ValueError("stop_loss debe estar entre 0 y 1")
    if any(not 0 < c.risk_per_trade <= 1 for c in configs):
        raise ValueError("risk_per_trade debe estar en (0, 1]")
    if any(bar.close <= 0 for bar in data):
        raise ValueError("Todos los precios deben ser positivos")

    eligible = tuple(c for c in configs if c.slow + 1 <= test_size)
    if not eligible:
        raise ValueError("Ningún candidato cabe en test_size; aumentalo o reducí slow")
    folds = []
    start = train_size
    number = 1
    while start + test_size <= len(data):
        train = data[start - train_size:start]
        test = data[start:start + test_size]
        ranked = []
        for candidate in eligible:
            result = backtest(
                train, fast=candidate.fast, slow=candidate.slow,
                initial_cash=initial_cash, fee_rate=fee_rate,
                stop_loss=candidate.stop_loss,
                risk_per_trade=candidate.risk_per_trade,
            )
            if result["closed_trades"] >= min_trades:
                ranked.append((_score(result), candidate.name, candidate, result))
        if not ranked:
            selected = None
            test_return = 0.0
            test_dd = 0.0
            test_trades = 0
            training_score = None
        else:
            _, _, selected, train_result = max(ranked, key=lambda item: (item[0], item[1]))
            test_result = backtest(
                test, fast=selected.fast, slow=selected.slow,
                initial_cash=initial_cash, fee_rate=fee_rate,
                stop_loss=selected.stop_loss,
                risk_per_trade=selected.risk_per_trade,
            )
            test_return = _liquidated_return(test_result, test, fee_rate)
            test_dd = float(test_result["max_drawdown_pct"])
            test_trades = int(test_result["closed_trades"])
            training_score = _score(train_result)
        folds.append({
            "fold": number,
            "train_start": train[0].date, "train_end": train[-1].date,
            "test_start": test[0].date, "test_end": test[-1].date,
            "selected": selected.name if selected else "SIN CANDIDATO",
            "training_score": training_score,
            "test_return_pct": test_return,
            "test_drawdown_pct": test_dd,
            "test_closed_trades": test_trades,
        })
        number += 1
        start += step
    if not folds:
        raise ValueError("No alcanza el historial para una ventana completa")
    valid = [f for f in folds if f["selected"] != "SIN CANDIDATO"]
    returns = [f["test_return_pct"] for f in valid]
    selected_counts: dict[str, int] = {}
    for fold in valid:
        selected_counts[fold["selected"]] = selected_counts.get(fold["selected"], 0) + 1
    return {
        "folds": folds,
        "fold_count": len(folds),
        "valid_folds": len(valid),
        "average_oos_return_pct": statistics.mean(returns) if returns else 0.0,
        "median_oos_return_pct": statistics.median(returns) if returns else 0.0,
        "positive_oos_folds": sum(x > 0 for x in returns),
        "worst_oos_drawdown_pct": min((f["test_drawdown_pct"] for f in valid), default=0.0),
        "selected_configuration_counts": dict(sorted(selected_counts.items())),
        "automatic_parameter_changes": False,
        "deployment_authorized": False,
        "decision": "SOLO INVESTIGACIÓN; no desplegar automáticamente",
        "warning": (
            "La selección usa solo entrenamiento y la evaluación usa ventanas posteriores. "
            "Los folds pueden solaparse; el resultado no garantiza rendimiento futuro."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Laboratorio de experimentos controlados")
    parser.add_argument("csv", help="CSV date,close")
    parser.add_argument("--train", type=int, default=180)
    parser.add_argument("--test", type=int, default=60)
    parser.add_argument("--step", type=int)
    parser.add_argument("--cash", type=float, default=10_000)
    parser.add_argument("--fee", type=float, default=0.001)
    parser.add_argument("--min-trades", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_experiments(
        load_bars(args.csv), train_size=args.train, test_size=args.test,
        step_size=args.step, initial_cash=args.cash, fee_rate=args.fee,
        min_trades=args.min_trades,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    print("HUGO-TRADER — LABORATORIO DE EXPERIMENTOS (paper only)")
    for fold in report["folds"]:
        print(f"Fold {fold['fold']}: {fold['selected']} | "
              f"TEST {fold['test_return_pct']:.2f}% | "
              f"DD {fold['test_drawdown_pct']:.2f}% | "
              f"operaciones {fold['test_closed_trades']}")
    print(f"Ventanas válidas: {report['valid_folds']}/{report['fold_count']}")
    print(f"Promedio OOS: {report['average_oos_return_pct']:.2f}% | "
          f"mediana: {report['median_oos_return_pct']:.2f}%")
    print(f"Ventanas positivas: {report['positive_oos_folds']}")
    print(f"Peor drawdown: {report['worst_oos_drawdown_pct']:.2f}%")
    print("Configuraciones seleccionadas:")
    for name, count in report["selected_configuration_counts"].items():
        print(f"- {name}: {count}")
    print(report["decision"])
    print(report["warning"])


if __name__ == "__main__":
    main()
