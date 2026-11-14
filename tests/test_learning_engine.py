import tempfile
import unittest
from pathlib import Path

from learning_engine import build_report, load_trade_rows


class LearningEngineTests(unittest.TestCase):
    def test_strategy_stats_and_conservative_lessons(self):
        rows = [
            {"strategy": "SMA 3/10", "pnl": -10, "exit_reason": "signal"},
            {"strategy": "SMA 3/10", "pnl": 20, "exit_reason": "signal"},
            {"strategy": "SMA 3/10", "pnl": -5, "exit_reason": "signal"},
        ]
        report = build_report(rows, min_samples=5)
        stats = report["by_strategy"]["SMA 3/10"]
        self.assertEqual(stats["trades"], 3)
        self.assertEqual(stats["wins"], 1)
        self.assertEqual(stats["losses"], 2)
        self.assertAlmostEqual(stats["net_pnl"], 5)
        self.assertFalse(report["automatic_parameter_changes"])
        self.assertFalse(report["live_trading_enabled"])
        self.assertTrue(any("muestra pequeña" in lesson for lesson in report["lessons"]))

    def test_empty_report_is_safe(self):
        report = build_report([])
        self.assertEqual(report["total_trades"], 0)
        self.assertEqual(report["overall"]["expectancy"], 0)
        self.assertTrue(report["lessons"])

    def test_load_existing_memory_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "memory.sqlite3"
            import sqlite3
            with sqlite3.connect(db) as conn:
                conn.execute("""CREATE TABLE trades (
                    id INTEGER PRIMARY KEY, strategy TEXT, entry_date TEXT,
                    exit_date TEXT, entry_price REAL, exit_price REAL, pnl REAL,
                    pnl_pct REAL, outcome TEXT, exit_reason TEXT)""")
                conn.execute("""INSERT INTO trades VALUES
                    (1,'SMA 10/50','2025-01-01','2025-01-03',100,110,9,10,'WIN','signal')""")
            rows = load_trade_rows(db)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["strategy"], "SMA 10/50")


if __name__ == "__main__":
    unittest.main()
