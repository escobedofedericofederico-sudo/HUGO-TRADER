import unittest

from market_context import classify_market_context


class MarketContextTests(unittest.TestCase):
    def test_detects_bullish_regime(self):
        result = classify_market_context([100 + i for i in range(25)])
        self.assertEqual(result["regime"], "alcista")
        self.assertFalse(result["uses_future_data"])

    def test_detects_bearish_regime(self):
        result = classify_market_context([200 - i for i in range(25)])
        self.assertEqual(result["regime"], "bajista")

    def test_reports_volatility_and_window(self):
        result = classify_market_context([100, 102, 98, 103, 97, 105, 99, 106, 98, 107,
                                          100, 108, 99, 109, 101, 110, 98, 111, 100, 112,
                                          99, 113])
        self.assertIn(result["volatility_state"], ("alta", "normal"))
        self.assertGreaterEqual(result["annualized_volatility"], 0)
        self.assertEqual(result["lookback"], 20)

    def test_rejects_short_or_invalid_history(self):
        with self.assertRaises(ValueError):
            classify_market_context([100, 101, 102])
        with self.assertRaises(ValueError):
            classify_market_context([100] * 20 + [0])


if __name__ == "__main__":
    unittest.main()
