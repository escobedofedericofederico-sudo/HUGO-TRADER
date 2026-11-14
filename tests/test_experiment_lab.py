import unittest

from bot import Bar, backtest
from experiment_lab import Candidate, _liquidated_result, run_experiments


class ExperimentLabTests(unittest.TestCase):
    def test_rejects_invalid_candidate(self):
        bars = [Bar(f"2025-01-{i:02d}", 100 + i) for i in range(1, 31)]
        with self.assertRaises(ValueError):
            run_experiments(bars, [Candidate(10, 5, None, 1.0)],
                            train_size=12, test_size=12)

    def test_requires_candidate_to_fit_both_windows(self):
        bars = [Bar(f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                    100 + i * 0.5 + (i % 7))
                for i in range(1, 101)]
        report = run_experiments(
            bars, [Candidate(3, 10, None, 1.0), Candidate(10, 50, None, 1.0)],
            train_size=20, test_size=60, step_size=60, min_trades=0,
        )
        self.assertEqual(report["fold_count"], 1)
        self.assertTrue(all("SMA 3/10" in fold["selected"] for fold in report["folds"]))

    def test_requires_candidate_to_fit_test_window(self):
        bars = [Bar(f"2025-{i // 28 + 1:02d}-{i % 28 + 1:02d}", 100 + i)
                for i in range(1, 80)]
        with self.assertRaises(ValueError):
            run_experiments(bars, [Candidate(10, 50, None, 1.0)],
                            train_size=55, test_size=20)

    def test_terminal_fee_is_included_in_test_drawdown(self):
        bars = [Bar(str(i), price) for i, price in enumerate(
            [10, 11, 12, 13, 14, 15, 16, 17]
        )]
        result = backtest(bars, fast=2, slow=3, initial_cash=1000, fee_rate=0.01)
        adjusted = _liquidated_result(result, bars, 0.01)
        self.assertLess(adjusted["return_pct"], result["return_pct"])
        self.assertLess(adjusted["max_drawdown_pct"], 0.0)
        self.assertEqual(adjusted["open_units"], 0.0)

    def test_runs_unseen_folds_without_enabling_deployment(self):
        bars = [Bar(f"2025-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                    100 + i * 0.5 + (i % 7))
                for i in range(1, 151)]
        report = run_experiments(
            bars, [Candidate(3, 10, None, 0.5)],
            train_size=40, test_size=20, step_size=20, min_trades=0,
        )
        self.assertGreaterEqual(report["fold_count"], 1)
        self.assertFalse(report["automatic_parameter_changes"])
        self.assertFalse(report["deployment_authorized"])
        self.assertEqual(len(report["folds"]), report["fold_count"])


if __name__ == "__main__":
    unittest.main()
