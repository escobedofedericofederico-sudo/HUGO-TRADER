"""Persistent experience memory for HUGO-TRADER.

Stores closed simulated trades and backtest outcomes in a local SQLite database.
It learns descriptive statistics from wins/losses; it does not train an ML model
or change trading parameters automatically.
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Iterable


def connect(db_path: str | Path = "hugo_memory.sqlite3") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            strategy TEXT NOT NULL,
            entry_date TEXT NOT NULL,
            exit_date TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL NOT NULL,
            pnl REAL NOT NULL,
            pnl_pct REAL NOT NULL,
            outcome TEXT NOT NULL,
            exit_reason TEXT NOT NULL,
            lesson TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY,
            fingerprint TEXT NOT NULL UNIQUE,
            strategy TEXT NOT NULL,
            initial_cash REAL NOT NULL,
            final_value REAL NOT NULL,
            return_pct REAL NOT NULL,
            max_drawdown_pct REAL NOT NULL,
            closed_trades INTEGER NOT NULL
        )
    """)
    conn.commit()
    return conn


def _outcome(pnl: float) -> str:
    if pnl > 1e-9:
        return "WIN"
    if pnl < -1e-9:
        return "LOSS"
    return "BREAKEVEN"


def _lesson(outcome: str, reason: str, pnl_pct: float) -> str:
    if outcome == "LOSS" and reason == "stop_loss":
        return "Stop-loss activado: revisar volatilidad, tamaño de posición y posibles gaps."
    if outcome == "LOSS" and reason == "signal":
        return "Salida por señal con pérdida: revisar señales falsas y mercado lateral."
    if outcome == "LOSS":
        return "Operación perdedora: revisar entrada, costes, contexto y ejecución."
    if outcome == "WIN" and reason == "take_profit":
        return "Ganancia por objetivo: comprobar si el objetivo captura suficiente tendencia."
    if outcome == "WIN":
        return "Operación ganadora: registrar contexto; una ganancia aislada no demuestra ventaja."
    return "Resultado neutro: considerar comisiones y si la operación aportó valor."


def record_backtest(
    trades: Iterable,
    strategy: str,
    result: dict,
    db_path: str | Path = "hugo_memory.sqlite3",
) -> dict:
    conn = connect(db_path)
    added = 0
    open_trade = None
    for trade in trades:
        if trade.action == "BUY":
            open_trade = trade
        elif trade.action == "SELL" and open_trade is not None:
            pnl = float(trade.pnl)
            pnl_pct = (trade.price / max(open_trade.price, 1e-12) - 1.0) * 100.0
            outcome = _outcome(pnl)
            fingerprint = "|".join((strategy, open_trade.date, trade.date,
                                    f"{open_trade.price:.10g}", f"{trade.price:.10g}"))
            cursor = conn.execute("""
                INSERT OR IGNORE INTO trades
                (fingerprint, strategy, entry_date, exit_date, entry_price,
                 exit_price, pnl, pnl_pct, outcome, exit_reason, lesson)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (fingerprint, strategy, open_trade.date, trade.date,
                  open_trade.price, trade.price, pnl, pnl_pct, outcome,
                  trade.reason, _lesson(outcome, trade.reason, pnl_pct)))
            added += cursor.rowcount
            open_trade = None

    exp_fingerprint = "|".join((strategy, str(result["initial_cash"]),
                                str(result["final_value"]), str(result["closed_trades"])))
    conn.execute("""
        INSERT OR IGNORE INTO experiments
        (fingerprint, strategy, initial_cash, final_value, return_pct,
         max_drawdown_pct, closed_trades)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (exp_fingerprint, strategy, result["initial_cash"], result["final_value"],
          result["return_pct"], result["max_drawdown_pct"], result["closed_trades"]))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    conn.close()
    return {"new_trades_saved": added, "total_memories": total}


def learning_report(db_path: str | Path = "hugo_memory.sqlite3",
                    min_samples: int = 5) -> dict:
    conn = connect(db_path)
    totals = conn.execute("""
        SELECT COUNT(*) AS n,
               SUM(outcome='WIN') AS wins,
               SUM(outcome='LOSS') AS losses,
               SUM(outcome='BREAKEVEN') AS flat,
               COALESCE(SUM(pnl), 0) AS net_pnl,
               COALESCE(AVG(pnl), 0) AS avg_pnl
        FROM trades
    """).fetchone()
    reasons = conn.execute("""
        SELECT exit_reason, COUNT(*) AS n,
               SUM(outcome='LOSS') AS losses,
               SUM(outcome='WIN') AS wins,
               COALESCE(AVG(pnl), 0) AS avg_pnl
        FROM trades GROUP BY exit_reason ORDER BY n DESC
    """).fetchall()
    strategies = conn.execute("""
        SELECT strategy, COUNT(*) AS n,
               SUM(outcome='LOSS') AS losses,
               SUM(outcome='WIN') AS wins,
               COALESCE(AVG(pnl), 0) AS avg_pnl
        FROM trades GROUP BY strategy ORDER BY n DESC
    """).fetchall()
    worst = conn.execute("""
        SELECT strategy, entry_date, exit_date, pnl, exit_reason, lesson
        FROM trades ORDER BY pnl ASC LIMIT 5
    """).fetchall()
    experiments = conn.execute("""
        SELECT strategy, return_pct, max_drawdown_pct, closed_trades
        FROM experiments ORDER BY return_pct DESC LIMIT 5
    """).fetchall()
    conn.close()

    n = totals["n"] or 0
    wins, losses, flat = totals["wins"] or 0, totals["losses"] or 0, totals["flat"] or 0
    recommendations = []
    for row in reasons:
        if row["n"] >= min_samples and row["losses"] / row["n"] >= 0.6:
            recommendations.append(
                f"Revisar salidas '{row['exit_reason']}': "
                f"{row['losses']}/{row['n']} terminaron en pérdida."
            )
    if n < min_samples:
        recommendations.append(
            f"Memoria aún pequeña: hacen falta al menos {min_samples} operaciones "
            "cerradas para emitir alertas estadísticas."
        )
    return {
        "total_trades": n, "wins": wins, "losses": losses, "breakeven": flat,
        "win_rate_pct": (wins / n * 100) if n else 0.0,
        "net_pnl": totals["net_pnl"], "average_pnl": totals["avg_pnl"],
        "by_exit_reason": [dict(row) for row in reasons],
        "by_strategy": [dict(row) for row in strategies],
        "worst_trades": [dict(row) for row in worst],
        "best_experiments": [dict(row) for row in experiments],
        "lessons": recommendations,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="HUGO-TRADER experience memory report")
    parser.add_argument("--db", default="hugo_memory.sqlite3")
    args = parser.parse_args()
    report = learning_report(args.db)
    print("HUGO-TRADER — MEMORIA DE EXPERIENCIAS (simulación)")
    print(f"Operaciones cerradas: {report['total_trades']}")
    print(f"Ganadas: {report['wins']} | Perdidas: {report['losses']} | Neutras: {report['breakeven']}")
    print(f"Tasa de acierto: {report['win_rate_pct']:.2f}%")
    print(f"PnL neto guardado: {report['net_pnl']:.2f} | PnL medio: {report['average_pnl']:.2f}")
    print("\nLECCIONES / ALERTAS")
    for lesson in report["lessons"]:
        print(f"- {lesson}")
    print("\nPEORES OPERACIONES")
    for trade in report["worst_trades"]:
        print(f"- {trade['strategy']} {trade['entry_date']}→{trade['exit_date']}: "
              f"{trade['pnl']:.2f} ({trade['exit_reason']}) — {trade['lesson']}")
    print("\nESTRATEGIAS POR RESULTADO")
    for item in report["by_strategy"]:
        print(f"- {item['strategy']}: {item['wins']} ganadas, {item['losses']} perdidas, "
              f"PnL medio {item['avg_pnl']:.2f}")
    print("\nLa memoria informa; no cambia reglas ni ejecuta órdenes automáticamente.")


if __name__ == "__main__":
    main()
