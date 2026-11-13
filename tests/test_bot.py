import unittest

from bot import Bar, backtest, moving_average


class BotTests(unittest.TestCase):
    def test_moving_average(self):
        self.assertEqual(moving_average([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])

    def test_backtest_returns_summary(self):
        prices = [10, 9, 8, 9, 10, 11, 12, 11, 10, 9, 8, 7]
        bars = [Bar(str(i), price) for i, price in enumerate(prices)]
        result = backtest(bars, fast=2, slow=3, initial_cash=1000, fee_rate=0)
        self.assertIn("final_value", result)
        self.assertGreaterEqual(result["final_value"], 0)

    def test_invalid_periods(self):
        with self.assertRaises(ValueError):
            backtest([Bar(str(i), 10) for i in range(5)], fast=3, slow=3)


if __name__ == "__main__":
    unittest.main()
