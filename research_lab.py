"""Walk-forward research lab for HUGO-TRADER (simulation only).

Each fold selects an SMA pair using only its training window, then evaluates
that selected pair on the immediately following, unseen test window.
"""
from __future__ import annotations

import argparse
import statistics
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
    buy_hold_test_return_pct: float
    edge_vs_buy_hold_pct: float
    test_drawdown_pct: float
    test_closed_trades: int
    capital_start_ars: float
    profit_ars: float
    capital_end_ars: float
    buy_hold_capital_end_ars: float


DEFAULT_CANDIDATES = ((3, 10), (5, 20), (8, 21), (10, 30), (10, 50))


def _score(result: dict) -> float:
    """Conservative training score: penalize drawdown, never inspect test data."""
    return result["return_pct"] - 0.5 * abs(result["max_drawdown_pct"])


def _charge_terminal_liquidation(result: dict, bars: list[Bar], fee_rate: float) -> dict:
    """Mark every test strategy flat at the final close and charge its exit fee."""
    adjusted = dict(result)
    units = float(result["open_units"])
    exit_fee = units * bars[-1].close * fee_rate
    final_value = float(result["final_value"]) - exit_fee
    adjusted["final_value"] = final_value
    adjusted["terminal_liquidation_fee"] = exit_fee
    adjusted["return_pct"] = (final_value / float(result["initial_cash"]) - 1.0) * 100.0

    # Include the liquidation fee in the final equity observation and drawdown.
    curve = list(result["equity_curve"])
    if curve:
        curve[-1] = final_value
        peak = curve[0]
        worst = 0.0
        for value in curve:
            peak = max(peak, value)
            if peak > 0:
                worst = min(worst, (value / peak - 1.0) * 100.0)
        adjusted["max_drawdown_pct"] = worst
    return adjusted


def _longest_streak(flags: list[bool]) -> int:
    """Return the longest consecutive run of True values."""
    best = current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        best = max(best, current)
    return best


def walk_forward(
    bars: Iterable[Bar],
    candidates: Iterable[tuple[int, int]] = DEFAULT_CANDIDATES,
    train_size: int = 120,
    test_size: int = 30,
    step_size: int | None = None,
    initial_cash: float = 10_000.0,
    fee_rate: float = 0.001,
    starting_capital_ars: float = 20_000.0,
) -> dict:
    data = list(bars)
    pairs = tuple((int(f), int(s)) for f, s in candidates)
    step = test_size if step_size is None else step_size
    if starting_capital_ars <= 0 or not 0 <= fee_rate < 1:
        raise ValueError("Capital must be positive and fee_rate must be in [0, 1)")
    if train_size < 12 or test_size < 3 or step < 1:
        raise ValueError("Use train_size >= 12, test_size >= 3 and step_size >= 1")
    if not pairs or any(f < 1 or s < 2 or f >= s for f, s in pairs):
        raise ValueError("Candidates must contain valid SMA pairs (fast < slow)")
    if any(b.close <= 0 for b in data):
        raise ValueError("All close prices must be positive")

    folds: list[FoldResult] = []
    test_start = train_size
    fold_no = 1
    simulated_capital_ars = float(starting_capital_ars)
    buy_hold_capital_ars = float(starting_capital_ars)
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
        # Force a fair comparison: both SMA and buy-and-hold are liquidated
        # at the final test close and pay an exit fee, even if SMA holds BTC.
        test_result = _charge_terminal_liquidation(test_result, test, fee_rate)
        capital_before = simulated_capital_ars
        profit_ars = capital_before * (test_result["return_pct"] / 100.0)
        simulated_capital_ars = capital_before + profit_ars
        # Benchmark buys at the first test close and liquidates at the last,
        # charging the same fee on entry and exit.
        benchmark_return = ((test[-1].close * (1 - fee_rate)) / (test[0].close * (1 + fee_rate)) - 1) * 100
        buy_hold_capital_ars *= 1 + benchmark_return / 100
        folds.append(FoldResult(
            fold=fold_no,
            train_start=train[0].date, train_end=train[-1].date,
            test_start=test[0].date, test_end=test[-1].date,
            selected_fast=chosen_fast, selected_slow=chosen_slow,
            train_return_pct=train_result["return_pct"],
            test_return_pct=test_result["return_pct"],
            buy_hold_test_return_pct=benchmark_return,
            edge_vs_buy_hold_pct=test_result["return_pct"] - benchmark_return,
            test_drawdown_pct=test_result["max_drawdown_pct"],
            test_closed_trades=test_result["closed_trades"],
            capital_start_ars=capital_before,
            profit_ars=profit_ars,
            capital_end_ars=simulated_capital_ars,
            buy_hold_capital_end_ars=buy_hold_capital_ars,
        ))
        fold_no += 1
        test_start += step

    if not folds:
        raise ValueError("Not enough rows for one complete train + test fold")

    returns = [f.test_return_pct for f in folds]
    # Aggregate outcomes by the SMA pair selected in training. This is
    # descriptive feedback only; it never changes parameters using test data.
    pair_performance = {}
    for fold in folds:
        key = f"SMA {fold.selected_fast}/{fold.selected_slow}"
        pair_performance.setdefault(key, []).append(fold)
    pair_diagnostics = {
        key: {
            "folds": len(items),
            "wins": sum(item.test_return_pct > 0 for item in items),
            "losses": sum(item.test_return_pct < 0 for item in items),
            "average_test_return_pct": sum(item.test_return_pct for item in items) / len(items),
            "average_edge_vs_buy_hold_pct": sum(item.edge_vs_buy_hold_pct for item in items) / len(items),
            "worst_drawdown_pct": min(item.test_drawdown_pct for item in items),
        }
        for key, items in sorted(pair_performance.items())
    }
    loss_lessons = []
    for key, stats in pair_diagnostics.items():
        if stats["losses"]:
            loss_lessons.append(
                f"{key}: {stats['losses']} pérdidas en {stats['folds']} ventanas; "
                f"promedio OOS {stats['average_test_return_pct']:.2f}% "
                f"y ventaja media vs BTC {stats['average_edge_vs_buy_hold_pct']:+.2f} pp. "
                "Revisar si la señal llega tarde en cambios de tendencia."
            )
    if any(f.test_drawdown_pct < -10 for f in folds):
        loss_lessons.append("Hubo una ventana con drawdown superior al 10%; probar límites de riesgo y gaps.")
    if not loss_lessons:
        loss_lessons.append("No hubo pérdidas en estas ventanas; ampliar muestra antes de concluir que el riesgo es bajo.")
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
        "starting_capital_ars": starting_capital_ars,
        "ending_capital_ars": simulated_capital_ars,
        "buy_hold_ending_capital_ars": buy_hold_capital_ars,
        "buy_hold_compounded_return_pct": (buy_hold_capital_ars / starting_capital_ars - 1) * 100,
        "strategy_edge_vs_buy_hold_ars": simulated_capital_ars - buy_hold_capital_ars,
        "strategy_wins_vs_buy_hold_folds": sum(f.edge_vs_buy_hold_pct > 0 for f in folds),
        "losing_folds": sum(f.test_return_pct < 0 for f in folds),
        "loss_lessons": loss_lessons,
        "pair_diagnostics": pair_diagnostics,
        "net_profit_ars": simulated_capital_ars - starting_capital_ars,
        "compounded_return_pct": (simulated_capital_ars / starting_capital_ars - 1) * 100,
        "worst_test_return_pct": min(returns),
        "median_test_return_pct": statistics.median(returns),
        "test_return_std_pct": statistics.pstdev(returns),
        "longest_losing_streak": _longest_streak([value < 0 for value in returns]),
        "edge_positive_folds": sum(f.edge_vs_buy_hold_pct > 0 for f in folds),
        "edge_positive_rate_pct": sum(f.edge_vs_buy_hold_pct > 0 for f in folds) / len(folds) * 100,
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
    parser.add_argument("--capital-ars", type=float, default=20_000,
                        help="Capital inicial de referencia en pesos argentinos; tipo de cambio constante")
    parser.add_argument("--fee", type=float, default=0.001)
    args = parser.parse_args()
    report = walk_forward(load_bars(args.csv), train_size=args.train,
                          test_size=args.test, step_size=args.step,
                          initial_cash=args.cash, fee_rate=args.fee,
                          starting_capital_ars=args.capital_ars)
    print("HUGO-TRADER — WALK-FORWARD (solo simulación)")
    for fold in report["folds"]:
        print(f"Fold {fold['fold']}: SMA {fold['selected_fast']}/{fold['selected_slow']} | "
              f"train {fold['train_return_pct']:.2f}% | "
              f"TEST {fold['test_return_pct']:.2f}% | "
              f"BTC hold {fold['buy_hold_test_return_pct']:.2f}% | "
              f"ventaja {fold['edge_vs_buy_hold_pct']:+.2f} pp | "
              f"DD test {fold['test_drawdown_pct']:.2f}%")
    print(f"Promedio fuera de muestra: {report['average_test_return_pct']:.2f}%")
    print(f"Folds positivos: {report['positive_test_folds']}/{report['fold_count']}")
    print(f"Mediana OOS: {report['median_test_return_pct']:.2f}% | Variabilidad: {report['test_return_std_pct']:.2f} pp")
    print(f"Racha máxima de pérdidas: {report['longest_losing_streak']} ventanas")
    print(f"Ventanas que superaron BTC: {report['edge_positive_folds']}/{report['fold_count']} ({report['edge_positive_rate_pct']:.1f}%)")
    print(f"BTC comprar y mantener: ${report['buy_hold_ending_capital_ars']:,.2f} ({report['buy_hold_compounded_return_pct']:.2f}%)")
    print(f"Ventaja neta vs BTC hold: ${report['strategy_edge_vs_buy_hold_ars']:+,.2f}; superó a BTC en {report['strategy_wins_vs_buy_hold_folds']}/{report['fold_count']} ventanas")
    print("DIAGNÓSTICO POR ESTRATEGIA ELEGIDA EN TRAINING:")
    for pair, stats in report["pair_diagnostics"].items():
        print(f"- {pair}: {stats['wins']} ganadoras / {stats['losses']} perdedoras "
              f"en {stats['folds']} ventanas | promedio OOS "
              f"{stats['average_test_return_pct']:.2f}% | "
              f"ventaja media vs BTC {stats['average_edge_vs_buy_hold_pct']:+.2f} pp")
    print("LECCIONES DE VENTANAS PERDEDORAS:")
    for lesson in report["loss_lessons"]:
        print(f"- {lesson}")
    print("\nSIMULACIÓN COMPUESTA — CAPITAL TEÓRICO EN ARS")
    print(f"Capital inicial: ${report['starting_capital_ars']:,.2f}")
    print(f"Capital final:   ${report['ending_capital_ars']:,.2f}")
    print(f"Ganancia/Pérdida: ${report['net_profit_ars']:+,.2f} ({report['compounded_return_pct']:.2f}%)")
    for fold in report["folds"]:
        print(f"  Fold {fold['fold']:02d}: ${fold['capital_start_ars']:,.2f} → ${fold['capital_end_ars']:,.2f} ({fold['profit_ars']:+,.2f} ARS)")
    print("Supuesto: dólar constante; no incluye variación ARS/USD ni costos locales de conversión.")
    print(report["decision"])
    print(report["warning"])


if __name__ == "__main__":
    main()
