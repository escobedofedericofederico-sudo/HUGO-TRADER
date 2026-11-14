"""HUGO-TRADER controlled learning diagnostics.

Reads the existing SQLite experience database and optionally attributes trades
to the market regime known immediately BEFORE entry. It never changes a
strategy, places orders, or treats historical statistics as a forecast.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from bot import load_bars
from market_context import classify_market_context


def _stats(rows: list[dict]) -> dict:
    pnls = [float(row["pnl"]) for row in rows]
    wins = [p for p in pnls if p > 1e-9]
    losses = [-p for p in pnls if p < -1e-9]
    gross_profit, gross_loss = sum(wins), sum(losses)
    count = len(pnls)
    return {
        "trades": count,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": count - len(wins) - len(losses),
        "win_rate_pct": len(wins) / count * 100 if count else 0.0,
        "net_pnl": sum(pnls),
        "average_pnl": sum(pnls) / count if count else 0.0,
        "average_win": sum(wins) / len(wins) if wins else 0.0,
        "average_loss": sum(losses) / len(losses) if losses else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (
            None if not gross_profit else "infinity"
        ),
        "expectancy": sum(pnls) / count if count else 0.0,
    }


def load_trade_rows(db_path: str | Path) -> list[dict]:
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"No existe la memoria: {path}")
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT strategy, entry_date, exit_date, entry_price, exit_price,
                   pnl, pnl_pct, outcome, exit_reason
            FROM trades ORDER BY exit_date, id
        """).fetchall()
    return [dict(row) for row in rows]


def _attribute_regime(rows: list[dict], prices_path: str | Path) -> list[dict]:
    bars = load_bars(prices_path)
    dates = {bar.date: index for index, bar in enumerate(bars)}
    enriched = []
    for row in rows:
        item = dict(row)
        index = dates.get(row["entry_date"])
        # Only use prices strictly before entry; never the entry bar or later.
        if index is None or index < 21:
            item["regime"] = "desconocido"
            item["volatility"] = "desconocida"
        else:
            context = classify_market_context(
                [bar.close for bar in bars[:index]], lookback=20
            )
            item["regime"] = context["regime"]
            item["volatility"] = context["volatility_state"]
        enriched.append(item)
    return enriched


def build_report(rows: Iterable[dict], min_samples: int = 10) -> dict:
    data = [dict(row) for row in rows]
    if min_samples < 1:
        raise ValueError("min_samples debe ser al menos 1")
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    by_reason: dict[str, list[dict]] = defaultdict(list)
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for row in data:
        by_strategy[str(row["strategy"])].append(row)
        by_reason[str(row["exit_reason"])].append(row)
        regime = str(row.get("regime", "no_disponible"))
        volatility = str(row.get("volatility", "no_disponible"))
        by_regime[f"{regime} / volatilidad {volatility}"].append(row)

    strategies = {key: _stats(value) for key, value in sorted(by_strategy.items())}
    reasons = {key: _stats(value) for key, value in sorted(by_reason.items())}
    regimes = {key: _stats(value) for key, value in sorted(by_regime.items())}
    lessons = []
    for name, stats in strategies.items():
        if stats["trades"] < min_samples:
            lessons.append(
                f"{name}: muestra pequeña ({stats['trades']}/{min_samples}); "
                "no sacar conclusiones todavía."
            )
        elif stats["expectancy"] < 0:
            lessons.append(
                f"{name}: expectativa negativa ({stats['expectancy']:.2f} por operación); "
                "mantener en observación y revisar entradas/salidas."
            )
        elif stats["profit_factor"] not in (None, "infinity") and stats["profit_factor"] < 1.2:
            lessons.append(
                f"{name}: expectativa positiva pero factor de beneficio débil; "
                "exigir más pruebas fuera de muestra."
            )
        else:
            lessons.append(
                f"{name}: estadísticas históricas favorables, aún no suficientes "
                "para autorizar dinero real."
            )
    for name, stats in reasons.items():
        if stats["trades"] >= min_samples and stats["losses"] / stats["trades"] >= 0.6:
            lessons.append(
                f"Salida '{name}': {stats['losses']}/{stats['trades']} pérdidas; "
                "revisar el mecanismo de salida."
            )
    if not data:
        lessons.append("Memoria vacía: ejecutá un backtest antes de analizar experiencias.")
    return {
        "total_trades": len(data),
        "overall": _stats(data) if data else _stats([]),
        "by_strategy": strategies,
        "by_exit_reason": reasons,
        "by_market_context": regimes,
        "lessons": lessons,
        "automatic_parameter_changes": False,
        "live_trading_enabled": False,
        "disclaimer": (
            "Diagnóstico descriptivo. Backtests solapados no son muestras independientes; "
            "las estadísticas no predicen rendimientos futuros."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnóstico controlado de aprendizaje")
    parser.add_argument("--db", default="hugo_memory.sqlite3")
    parser.add_argument("--prices", help="CSV date,close para atribuir contexto previo a cada entrada")
    parser.add_argument("--min-samples", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Imprimir informe JSON")
    args = parser.parse_args()
    rows = load_trade_rows(args.db)
    if args.prices:
        rows = _attribute_regime(rows, args.prices)
    report = build_report(rows, args.min_samples)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    print("HUGO-TRADER — MOTOR DE DIAGNÓSTICO (solo simulación)")
    print(f"Operaciones analizadas: {report['total_trades']}")
    overall = report["overall"]
    print(f"Acierto: {overall['win_rate_pct']:.2f}% | "
          f"Expectativa: {overall['expectancy']:.2f} | "
          f"PnL neto: {overall['net_pnl']:.2f}")
    print("\nPOR ESTRATEGIA")
    for name, stats in report["by_strategy"].items():
        pf = stats["profit_factor"]
        pf_text = "sin pérdidas" if pf == "infinity" else ("N/D" if pf is None else f"{pf:.2f}")
        print(f"- {name}: {stats['wins']}G/{stats['losses']}P, "
              f"acierto {stats['win_rate_pct']:.1f}%, "
              f"media {stats['average_pnl']:.2f}, PF {pf_text}")
    print("\nCONTEXTO DE MERCADO")
    for name, stats in report["by_market_context"].items():
        print(f"- {name}: {stats['trades']} operaciones, "
              f"PnL medio {stats['average_pnl']:.2f}, "
              f"acierto {stats['win_rate_pct']:.1f}%")
    print("\nLECCIONES")
    for lesson in report["lessons"]:
        print(f"- {lesson}")
    print("\nNo modifica parámetros ni ejecuta órdenes reales.")
    print(report["disclaimer"])


if __name__ == "__main__":
    main()
