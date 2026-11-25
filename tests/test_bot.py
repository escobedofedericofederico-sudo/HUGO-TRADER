import os
import tempfile
import unittest

from bot import Bar, Trade, backtest, load_bars, moving_average
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

    def test_backtest_rejects_non_finite_prices(self):
        bars = self.make_bars([10, 11, 12, float("nan")])
        with self.assertRaises(ValueError):
            backtest(bars, fast=2, slow=3)

    def test_csv_loader_rejects_non_finite_prices(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write("date,close\n2025-01-01,inf\n")
            path = handle.name
        try:
            with self.assertRaises(ValueError):
                load_bars(path)
        finally:
            os.unlink(path)

    def test_csv_loader_accepts_strictly_increasing_iso_dates(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write("date,close\\n2025-01-01,100\\n2025-01-02,101\\n")
            path = handle.name
        try:
            bars = load_bars(path)
            self.assertEqual([bar.date for bar in bars], ["2025-01-01", "2025-01-02"])
            self.assertEqual([bar.close for bar in bars], [100.0, 101.0])
        finally:
            os.unlink(path)

    def test_csv_loader_rejects_invalid_dates(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
            handle.write("date,close\\nnot-a-date,100\\n")
            path = handle.name
        try:
            with self.assertRaisesRegex(ValueError, "ISO calendar date"):
                load_bars(path)
        finally:
            os.unlink(path)

    def test_csv_loader_rejects_duplicate_and_out_of_order_dates(self):
        fixtures = (
            "date,close\\n2025-01-01,100\\n2025-01-01,101\\n",
            "date,close\\n2025-01-02,101\\n2025-01-01,100\\n",
        )
        for csv_text in fixtures:
            with self.subTest(csv_text=csv_text):
                with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as handle:
                    handle.write(csv_text)
                    path = handle.name
                try:
                    with self.assertRaisesRegex(ValueError, "strictly increasing"):
                        load_bars(path)
                finally:
                    os.unlink(path)

    def test_stop_risk_budget_controls_position_notional(self):
        prices = [10, 9, 8, 9, 10, 11, 12, 13]
        result = backtest(
            self.make_bars(prices), fast=2, slow=3,
            initial_cash=1000, fee_rate=0, stop_loss=0.05,
            risk_per_trade=0.01,
        )
        buy = next(trade for trade in result["trades"] if trade.action == "BUY")
        self.assertAlmostEqual(result["open_units"] * buy.price, 200.0)

    def test_stop_risk_budget_includes_entry_and_exit_fees(self):
        prices = [10, 9, 8, 9, 10, 11, 10.45]
        result = backtest(
            self.make_bars(prices), fast=2, slow=3,
            initial_cash=1000, fee_rate=0.001, stop_loss=0.05,
            risk_per_trade=0.01,
        )
        sells = [trade for trade in result["trades"] if trade.action == "SELL"]
        self.assertEqual(len(sells), 1)
        self.assertEqual(sells[0].reason, "stop_loss")
        # The 1% budget is $10; both entry and exit fees must fit inside it.
        self.assertAlmostEqual(sells[0].pnl, -10.0, places=8)

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
    def make_bars(self, prices):
        return [Bar(str(i), price) for i, price in enumerate(prices)]

    def test_walk_forward_charges_terminal_exit_fee_to_open_strategy(self):
        from research_lab import _charge_terminal_liquidation
        bars = [Bar(str(i), price) for i, price in enumerate([10, 11, 12, 13, 14, 15, 16, 17])]
        result = backtest(bars, fast=2, slow=3, initial_cash=1000, fee_rate=0.01)
        self.assertGreater(result["open_units"], 0)
        adjusted = _charge_terminal_liquidation(result, bars, 0.01)
        expected_fee = result["open_units"] * bars[-1].close * 0.01
        self.assertAlmostEqual(adjusted["terminal_liquidation_fee"], expected_fee)
        self.assertAlmostEqual(adjusted["final_value"], result["final_value"] - expected_fee)
        self.assertLess(adjusted["return_pct"], result["return_pct"])
        self.assertLess(adjusted["max_drawdown_pct"], 0.0)
        self.assertEqual(adjusted["open_units"], 0.0)

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
        self.assertIn("pair_diagnostics", report)
        self.assertTrue(report["loss_lessons"])
        self.assertIn("median_test_return_pct", report)
        self.assertIn("test_return_std_pct", report)
        self.assertIn("longest_losing_streak", report)
        self.assertIn("edge_positive_rate_pct", report)
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
        self.assertTrue(all("buy_hold_test_return_pct" in fold for fold in report["folds"]))
        self.assertTrue(all("edge_vs_buy_hold_pct" in fold for fold in report["folds"]))
        self.assertGreater(report["buy_hold_ending_capital_ars"], 0)
        self.assertEqual(report["strategy_wins_vs_buy_hold_folds"], sum(
            fold["edge_vs_buy_hold_pct"] > 0 for fold in report["folds"]))

    def test_walk_forward_rejects_insufficient_history(self):
        from research_lab import walk_forward
        with self.assertRaises(ValueError):
            walk_forward([Bar(str(i), 100 + i) for i in range(30)],
                         candidates=((2, 5),), train_size=20, test_size=20)

    def test_walk_forward_requires_market_context_history(self):
        from research_lab import walk_forward
        with self.assertRaisesRegex(ValueError, "train_size >= 21"):
            walk_forward([Bar(str(i), 100 + i) for i in range(80)],
                         candidates=((2, 5),), train_size=20, test_size=20)

    def test_walk_forward_rejects_invalid_candidates(self):
        from research_lab import walk_forward
        with self.assertRaises(ValueError):
            walk_forward([Bar(str(i), 100 + i) for i in range(80)],
                         candidates=((5, 5),), train_size=40, test_size=20)


class RobustnessMetricTests(unittest.TestCase):
    def test_longest_losing_streak(self):
        from research_lab import _longest_streak
        self.assertEqual(_longest_streak([False, True, True, False, True]), 2)
        self.assertEqual(_longest_streak([False, False]), 0)
