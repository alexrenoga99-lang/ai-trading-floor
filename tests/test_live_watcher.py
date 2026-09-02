import os
import tempfile
import unittest

import pandas as pd

from live.watcher import build_signal_from_recent_candles, log_signal


class LiveWatcherTests(unittest.TestCase):
    def test_build_signal_returns_required_fields(self):
        strategy = {
            "strategy_id": "nas100_ob_choch_v1",
            "risk_amount_usd": 100,
            "account_size": 10000,
            "reward_to_risk": {"fixed": 3.0},
        }
        candles = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=12, freq="min"),
                "open": [100, 101, 102, 103, 104, 105, 104, 106, 107, 108, 109, 110],
                "high": [101, 102, 103, 104, 105, 106, 105, 107, 108, 109, 110, 111],
                "low": [99, 100, 101, 102, 103, 104, 103, 105, 106, 107, 108, 109],
                "close": [100.5, 101.2, 102.1, 103.4, 104.5, 105.8, 104.3, 106.4, 107.7, 108.6, 109.3, 110.2],
                "volume": [10, 12, 15, 18, 20, 22, 19, 23, 25, 27, 29, 30],
            }
        )

        signal = build_signal_from_recent_candles(strategy, candles)

        self.assertIsNotNone(signal)
        for key in ["strategy_id", "direction", "entry_price", "stop_price", "target_price", "position_size", "timestamp"]:
            self.assertIn(key, signal)
        self.assertGreater(signal["entry_price"], 0)
        self.assertGreater(signal["target_price"], signal["entry_price"])

    def test_build_signal_works_for_recent_trend_not_strictly_monotonic(self):
        strategy = {
            "strategy_id": "nas100_ob_choch_v1",
            "risk_amount_usd": 100,
            "account_size": 10000,
            "reward_to_risk": {"fixed": 3.0},
        }
        candles = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=8, freq="min"),
                "open": [99.8, 101.1, 99.5, 100.8, 98.5, 100.1, 99.2, 100.9],
                "high": [100.6, 101.8, 100.1, 101.4, 99.7, 101.3, 100.4, 102.4],
                "low": [99.2, 100.4, 98.6, 99.4, 97.9, 99.5, 98.7, 100.1],
                "close": [100.2, 101.4, 99.7, 100.5, 98.9, 100.6, 99.8, 101.2],
                "volume": [10, 11, 9, 12, 8, 11, 10, 13],
            }
        )

        signal = build_signal_from_recent_candles(strategy, candles)

        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "bullish")

    def test_log_signal_writes_csv(self):
        signal = {
            "strategy_id": "nas100_ob_choch_v1",
            "direction": "bullish",
            "entry_price": 100.0,
            "stop_price": 99.0,
            "target_price": 103.0,
            "position_size": 0.5,
            "timestamp": "2024-01-01T00:00:00Z",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "signals_log.csv")
            log_signal(signal, csv_path=path)
            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
            self.assertIn("strategy_id", content)
            self.assertIn("bullish", content)


if __name__ == "__main__":
    unittest.main()
