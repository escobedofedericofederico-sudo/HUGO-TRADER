import os
import tempfile
import unittest

from bot import Bar, Trade, backtest, moving_average
from experience import learning_report, record_backtest


class BotTests(unittest.TestCase):
    def make_bars(self, prices):
        return [Bar(str(i), price) for i, price in enumerate(prices)]

    def test_moving_average(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_moving_average_rejects_zero_period(self):
        with self.assertRaises(ValueError):
            moving_average([1, 2], 0)

    def test_backtest_returns_risk_metrics(self):
        prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 7, 8, 9]
        result = backtest(self.make_bars(prices), fast=2, slow=3,
                          initial_cash=1000, fee_rate=0)
        for key in ("final_value", "return_pct", "max_drawdown_pct",
                    "win_rate_pct", "profit_factor", "buy_hold_return_pct"):
            self.assertIn(key, result)
        self.assertGreaterEqual(result["final_value"], 0)
        self.assertLessEqual(result["max_drawdown_pct"], 0)

    def test_stop_loss_closes_position(self):
        prices = [10, 9, 8, 9, 10, 11, 12, 10, 8, 7, 6]
        result = backtest(self.make_bars(prices), fast=2, slow=3,
                          initial_cash=1000, fee_rate=0, stop_loss=0.05)
        sells = [trade for trade in result["trades"] if trade.action == "SELL"]
        self.assertTrue(any(trade.reason == "stop_loss" for trade in sells))

    def test_take_profit_closes_position(self):
        prices = [10, 9, 8, 9, 10, 11, 12, 13, 14]
        result = backtest(self.make_bars(prices), fast=2, slow=3,
                          initial_cash=1000, fee_rate=0, take_profit=0.10)
        sells = [trade for trade in result["trades"] if trade.action == "SELL"]
        self.assertTrue(any(trade.reason == "take_profit" for trade in sells))

    def test_invalid_periods_and_risk(self):
        bars = self.make_bars([10] * 8)
        with self.assertRaises(ValueError):
            backtest(bars, fast=3, slow=3)
        with self.assertRaises(ValueError):
            backtest(bars, fast=2, slow=3, risk_per_trade=0)

    def test_invalid_stop_loss(self):
        with self.assertRaises(ValueError):
            backtest(self.make_bars([10] * 8), fast=2, slow=3, stop_loss=1)

    def test_memory_remembers_loss_and_prevents_duplicate(self):
        with tempfile.TemporaryDirectory() as directory:
            db = os.path.join(directory, "memory.sqlite3")
            trades = [Trade("day1", "BUY", 100, 0),
                      Trade("day2", "SELL", 90, 0, -10, "stop_loss")]
            result = {"initial_cash": 1000, "final_value": 990,
                      "return_pct": -1, "max_drawdown_pct": -1,
                      "closed_trades": 1}
            first = record_backtest(trades, "SMA 2/5", result, db)
            second = record_backtest(trades, "SMA 2/5", result, db)
            report = learning_report(db)
            self.assertEqual(first["new_trades_saved"], 1)
            self.assertEqual(second["new_trades_saved"], 0)
            self.assertEqual(report["losses"], 1)
            self.assertEqual(report["total_trades"], 1)
            self.assertEqual(report["worst_trades"][0]["exit_reason"], "stop_loss")

    def test_memory_identifies_repeated_loss_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            db = os.path.join(directory, "memory.sqlite3")
            for i in range(5):
                trades = [Trade(f"entry{i}", "BUY", 100, 0),
                          Trade(f"exit{i}", "SELL", 90, 0, -10, "stop_loss")]
                result = {"initial_cash": 1000, "final_value": 990,
                          "return_pct": -1, "max_drawdown_pct": -1,
                          "closed_trades": 1}
                record_backtest(trades, "SMA 2/5", result, db)
            report = learning_report(db)
            self.assertTrue(any("stop_loss" in lesson for lesson in report["lessons"]))


if __name__ == "__main__":
    unittest.main()


class ResearchLabTests(unittest.TestCase):
    def test_walk_forward_uses_multiple_unseen_test_folds(self):
        from research_lab import walk_forward
        prices = []
        value = 100.0
        for i in range(220):
            # Deterministic varied series with trends and reversals.
            drift = 0.35 if (i // 25) % 2 == 0 else -0.22
            value = max(10.0, value + drift + ((i % 7) - 3) * 0.08)
            prices.append(Bar(str(i), value))
        report = walk_forward(
            prices, candidates=((2, 5), (3, 8)),
            train_size=80, test_size=20, step_size=20,
        )
        self.assertGreaterEqual(report["fold_count"], 3)
        self.assertEqual(len(report["folds"]), report["fold_count"])
        for fold in report["folds"]:
            self.assertLess(int(fold["train_end"]), int(fold["test_start"]))
            self.assertIn((fold["selected_fast"], fold["selected_slow"]), ((2, 5), (3, 8)))


    def test_walk_forward_reports_compounded_ars_capital(self):
        from research_lab import walk_forward
        prices = []
        value = 100.0
        for i in range(220):
            drift = 0.35 if (i // 25) % 2 == 0 else -0.22
            value = max(10.0, value + drift + ((i % 7) - 3) * 0.08)
            prices.append(Bar(str(i), value))
        report = walk_forward(
            prices, candidates=((2, 5), (3, 8)),
            train_size=80, test_size=20, step_size=20,
            starting_capital_ars=20_000,
        )
        self.assertEqual(report["starting_capital_ars"], 20_000)
        self.assertAlmostEqual(
            report["ending_capital_ars"] - report["starting_capital_ars"],
            report["net_profit_ars"],
        )
        self.assertEqual(len(report["folds"]), report["fold_count"])
        self.assertTrue(all("profit_ars" in fold for fold in report["folds"]))

    def test_walk_forward_rejects_insufficient_history(self):
        from research_lab import walk_forward
        with self.assertRaises(ValueError):
            walk_forward([Bar(str(i), 100 + i) for i in range(30)],
                         candidates=((2, 5),), train_size=20, test_size=20)

    def test_walk_forward_rejects_invalid_candidates(self):
        from research_lab import walk_forward
        with self.assertRaises(ValueError):
            walk_forward([Bar(str(i), 100 + i) for i in range(80)],
                         candidates=((5, 5),), train_size=40, test_size=20)
