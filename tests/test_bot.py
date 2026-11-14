import unittest

from bot import Bar, backtest, moving_average


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
                          initial_cash=1000, fee_rate=0,
                          stop_loss=0.05)
        sells = [trade for trade in result["trades"] if trade.action == "SELL"]
        self.assertTrue(any(trade.reason == "stop_loss" for trade in sells))

    def test_take_profit_closes_position(self):
        prices = [10, 9, 8, 9, 10, 11, 12, 13, 14]
        result = backtest(self.make_bars(prices), fast=2, slow=3,
                          initial_cash=1000, fee_rate=0,
                          take_profit=0.10)
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


if __name__ == "__main__":
    unittest.main()
