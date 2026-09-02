import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import pandas as pd

from live.watcher import build_signal_from_recent_candles, log_signal, should_emit_signal


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

    def test_build_signal_uses_macro_context_and_minute_confirmation(self):
        strategy = {
            "strategy_id": "nas100_ob_choch_v1",
            "risk_amount_usd": 100,
            "account_size": 10000,
            "reward_to_risk": {"fixed": 3.0},
            "signal_config": {
                "lookback_bars": 5,
                "min_trend_strength_pct": 0.0002,
                "min_rr": 3.0,
                "liquidity_zone_tolerance": 0.001,
            },
        }
        macro_context = {
            "1h": pd.DataFrame(
                {
                    "timestamp": pd.date_range("2024-01-01", periods=12, freq="h"),
                    "open": [101.0, 101.5, 102.0, 102.5, 103.0, 103.4, 103.7, 104.0, 104.2, 104.6, 104.9, 105.3],
                    "high": [101.8, 102.3, 102.6, 103.1, 103.6, 104.1, 104.4, 104.8, 105.0, 105.5, 105.7, 106.0],
                    "low": [100.1, 100.8, 101.2, 101.6, 102.1, 102.5, 102.9, 103.2, 103.4, 103.9, 104.1, 104.5],
                    "close": [101.4, 101.9, 102.4, 102.9, 103.3, 103.8, 104.1, 104.5, 104.8, 105.2, 105.4, 105.8],
                    "volume": [10, 11, 12, 13, 15, 16, 17, 18, 19, 20, 21, 22],
                }
            ),
            "4h": pd.DataFrame(
                {
                    "timestamp": pd.date_range("2024-01-01", periods=10, freq="4h"),
                    "open": [99.0, 99.8, 100.5, 101.4, 102.2, 102.8, 103.5, 104.1, 104.7, 105.2],
                    "high": [99.8, 100.5, 101.2, 102.0, 102.8, 103.5, 104.2, 104.9, 105.6, 106.1],
                    "low": [98.2, 98.9, 99.7, 100.6, 101.3, 102.0, 102.7, 103.4, 104.0, 104.7],
                    "close": [99.2, 99.9, 100.8, 101.7, 102.4, 103.1, 103.8, 104.4, 105.0, 105.7],
                    "volume": [20, 21, 22, 23, 25, 26, 27, 28, 29, 30],
                }
            ),
        }
        candles = pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
                "open": [103.2, 103.3, 103.5, 103.6, 103.7, 103.8, 103.9, 104.0],
                "high": [103.5, 103.6, 103.8, 103.9, 104.0, 104.1, 104.2, 104.3],
                "low": [103.0, 103.1, 103.2, 103.3, 103.4, 103.5, 103.6, 103.7],
                "close": [103.2, 103.3, 103.5, 103.7, 103.8, 103.9, 104.0, 104.1],
                "volume": [10, 12, 11, 15, 16, 18, 20, 22],
            }
        )

        signal = build_signal_from_recent_candles(strategy, candles, timeframe="1m", macro_context=macro_context)

        self.assertIsNotNone(signal)
        self.assertEqual(signal["direction"], "bullish")
        self.assertTrue(signal.get("multi_tf_confirmed", False))

    def test_signal_requires_price_to_be_near_a_valid_macro_zone(self):
        strategy = {
            "strategy_id": "nas100_ob_choch_v1",
            "risk_amount_usd": 100,
            "account_size": 10000,
            "reward_to_risk": {"fixed": 3.0},
            "signal_config": {
                "lookback_bars": 5,
                "min_trend_strength_pct": 0.0002,
                "liquidity_zone_tolerance": 0.003,
                "require_1m_5m_alignment": True,
            },
        }
        macro_context = {
            "1h": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01", periods=20, freq="h"),
                "open": [100.1, 100.5, 100.9, 101.2, 101.8, 102.2, 102.6, 102.9, 103.1, 103.4, 103.8, 104.1, 104.4, 104.0, 103.7, 103.5, 103.9, 104.2, 104.7, 105.1],
                "high": [100.8, 101.2, 101.7, 102.1, 102.5, 102.9, 103.3, 103.6, 103.9, 104.2, 104.6, 104.9, 105.2, 104.7, 104.4, 104.1, 104.5, 104.8, 105.5, 105.9],
                "low": [99.6, 99.9, 100.3, 100.8, 101.2, 101.6, 102.0, 102.4, 102.7, 103.0, 103.3, 103.7, 104.0, 103.5, 103.2, 102.9, 103.1, 103.5, 104.0, 104.4],
                "close": [100.4, 100.8, 101.2, 101.7, 102.1, 102.5, 102.9, 103.2, 103.6, 103.9, 104.1, 104.5, 104.9, 104.2, 103.8, 103.6, 103.9, 104.4, 104.9, 105.3],
                "volume": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 20, 19, 18, 17, 18, 19, 20],
            }),
            "4h": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01", periods=8, freq="4h"),
                "open": [100.0, 100.6, 101.1, 101.7, 102.2, 102.8, 103.4, 103.9],
                "high": [100.7, 101.3, 101.9, 102.6, 103.1, 103.5, 104.0, 104.4],
                "low": [99.4, 99.9, 100.5, 101.0, 101.5, 102.0, 102.6, 103.1],
                "close": [100.2, 100.9, 101.4, 101.9, 102.7, 103.0, 103.6, 104.1],
                "volume": [20, 22, 23, 24, 25, 26, 27, 28],
            }),
            "1m": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
                "open": [102.9, 103.0, 103.2, 103.5, 103.8, 104.0, 104.2, 104.5],
                "high": [103.2, 103.3, 103.6, 103.9, 104.1, 104.3, 104.6, 104.9],
                "low": [102.6, 102.8, 103.1, 103.3, 103.6, 103.8, 104.0, 104.3],
                "close": [103.0, 103.1, 103.4, 103.7, 103.9, 104.2, 104.4, 104.7],
                "volume": [10, 11, 12, 13, 12, 14, 15, 16],
            }),
            "5m": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01 00:00:00", periods=6, freq="5min"),
                "open": [102.8, 103.0, 103.3, 103.5, 103.8, 104.1],
                "high": [103.1, 103.4, 103.6, 103.9, 104.3, 104.5],
                "low": [102.5, 102.8, 103.1, 103.3, 103.6, 103.9],
                "close": [103.0, 103.2, 103.5, 103.7, 103.9, 104.2],
                "volume": [20, 22, 24, 23, 25, 26],
            }),
        }
        candles = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
            "open": [104.6, 104.8, 104.9, 105.0, 105.1, 105.2, 105.3, 105.4],
            "high": [104.9, 105.0, 105.2, 105.4, 105.5, 105.6, 105.7, 105.8],
            "low": [104.3, 104.5, 104.6, 104.7, 104.8, 104.9, 105.1, 105.2],
            "close": [104.7, 104.9, 105.0, 105.1, 105.2, 105.3, 105.5, 105.6],
            "volume": [10, 11, 12, 13, 12, 14, 15, 16],
        })

        signal = build_signal_from_recent_candles(strategy, candles, timeframe="1m", macro_context=macro_context)

        self.assertIsNone(signal)

    def test_signal_requires_1m_and_5m_alignment(self):
        strategy = {
            "strategy_id": "nas100_ob_choch_v1",
            "risk_amount_usd": 100,
            "account_size": 10000,
            "reward_to_risk": {"fixed": 3.0},
            "signal_config": {
                "lookback_bars": 5,
                "min_trend_strength_pct": 0.0002,
                "liquidity_zone_tolerance": 0.001,
                "require_1m_5m_alignment": True,
            },
        }
        macro_context = {
            "1h": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01", periods=8, freq="h"),
                "open": [103.0, 103.1, 103.2, 103.3, 103.4, 103.5, 103.6, 103.7],
                "high": [103.4, 103.5, 103.6, 103.7, 103.8, 103.9, 104.0, 104.1],
                "low": [102.8, 102.9, 103.0, 103.1, 103.2, 103.3, 103.4, 103.5],
                "close": [103.1, 103.2, 103.3, 103.4, 103.5, 103.6, 103.7, 103.8],
                "volume": [10, 11, 12, 13, 14, 15, 16, 17],
            }),
            "4h": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01", periods=6, freq="4h"),
                "open": [102.6, 102.8, 103.0, 103.2, 103.4, 103.6],
                "high": [103.0, 103.2, 103.4, 103.6, 103.8, 104.0],
                "low": [102.4, 102.6, 102.8, 103.0, 103.2, 103.4],
                "close": [102.8, 103.0, 103.2, 103.4, 103.6, 103.8],
                "volume": [20, 21, 22, 23, 24, 25],
            }),
            "1m": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
                "open": [103.2, 103.3, 103.4, 103.5, 103.6, 103.7, 103.8, 103.9],
                "high": [103.4, 103.5, 103.6, 103.7, 103.8, 103.9, 104.0, 104.1],
                "low": [103.0, 103.1, 103.2, 103.3, 103.4, 103.5, 103.6, 103.7],
                "close": [103.3, 103.4, 103.5, 103.6, 103.7, 103.8, 103.9, 104.0],
                "volume": [10, 11, 12, 13, 12, 14, 15, 16],
            }),
            "5m": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01 00:00:00", periods=6, freq="5min"),
                "open": [103.1, 103.2, 103.4, 103.5, 103.7, 103.8],
                "high": [103.3, 103.5, 103.6, 103.8, 103.9, 104.1],
                "low": [102.9, 103.1, 103.2, 103.3, 103.5, 103.6],
                "close": [103.2, 103.4, 103.5, 103.7, 103.8, 103.9],
                "volume": [20, 22, 24, 23, 25, 26],
            }),
        }
        bearish_minute = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
            "open": [103.8, 103.7, 103.6, 103.5, 103.4, 103.3, 103.2, 103.1],
            "high": [103.9, 103.8, 103.7, 103.6, 103.5, 103.4, 103.3, 103.2],
            "low": [103.6, 103.5, 103.4, 103.3, 103.2, 103.1, 103.0, 102.9],
            "close": [103.7, 103.6, 103.5, 103.4, 103.3, 103.2, 103.1, 103.0],
            "volume": [10, 11, 12, 13, 12, 14, 15, 16],
        })

        macro_context["1m"] = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
            "open": [102.8, 102.9, 103.0, 103.1, 103.2, 103.3, 103.4, 103.5],
            "high": [103.0, 103.1, 103.2, 103.3, 103.4, 103.5, 103.6, 103.7],
            "low": [102.6, 102.7, 102.8, 102.9, 103.0, 103.1, 103.2, 103.3],
            "close": [102.9, 103.0, 103.1, 103.2, 103.3, 103.4, 103.5, 103.6],
            "volume": [10, 11, 12, 13, 12, 14, 15, 16],
        })
        macro_context["5m"] = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01 00:00:00", periods=6, freq="5min"),
            "open": [102.7, 102.9, 103.0, 103.1, 103.3, 103.4],
            "high": [103.0, 103.1, 103.3, 103.4, 103.5, 103.7],
            "low": [102.5, 102.7, 102.8, 103.0, 103.1, 103.2],
            "close": [102.8, 103.0, 103.2, 103.3, 103.4, 103.6],
            "volume": [20, 22, 24, 23, 25, 26],
        })

        bullish_signal = build_signal_from_recent_candles(strategy, macro_context["1m"], timeframe="1m", macro_context=macro_context)
        self.assertIsNotNone(bullish_signal)

        conflict_context = {**macro_context, "5m": bearish_minute}
        conflict_signal = build_signal_from_recent_candles(strategy, macro_context["1m"], timeframe="1m", macro_context=conflict_context)
        self.assertIsNone(conflict_signal)

    def test_signal_requires_real_breakout_outside_macro_zone(self):
        strategy = {
            "strategy_id": "nas100_ob_choch_v1",
            "risk_amount_usd": 100,
            "account_size": 10000,
            "reward_to_risk": {"fixed": 3.0},
            "signal_config": {"liquidity_zone_tolerance": 0.003, "require_1m_5m_alignment": True},
        }
        macro_context = {
            "1h": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01", periods=12, freq="h"),
                "open": [100.0, 100.2, 100.4, 100.3, 100.5, 100.7, 100.9, 101.1, 101.0, 101.2, 101.4, 101.6],
                "high": [100.5, 100.7, 100.8, 100.9, 101.1, 101.2, 101.4, 101.6, 101.5, 101.7, 101.9, 102.1],
                "low": [99.6, 99.8, 100.0, 99.9, 100.2, 100.3, 100.5, 100.7, 100.6, 100.9, 101.0, 101.2],
                "close": [100.2, 100.3, 100.6, 100.4, 100.8, 101.0, 101.2, 101.3, 101.1, 101.5, 101.7, 101.9],
                "volume": [10, 12, 11, 13, 12, 14, 15, 16, 15, 17, 18, 19],
            }),
            "4h": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01", periods=8, freq="4h"),
                "open": [99.7, 100.2, 100.5, 100.9, 101.3, 101.6, 101.9, 102.3],
                "high": [100.3, 100.7, 101.1, 101.4, 101.8, 102.0, 102.2, 102.9],
                "low": [99.4, 99.8, 100.1, 100.5, 100.9, 101.2, 101.5, 101.9],
                "close": [100.1, 100.5, 100.8, 101.1, 101.6, 101.9, 102.1, 102.5],
                "volume": [20, 21, 22, 23, 24, 25, 26, 27],
            }),
            "1m": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
                "open": [100.9, 101.0, 101.1, 101.2, 101.3, 101.4, 101.5, 101.6],
                "high": [101.2, 101.4, 101.5, 101.6, 101.7, 101.8, 101.9, 102.0],
                "low": [100.7, 100.8, 100.9, 101.0, 101.1, 101.2, 101.3, 101.4],
                "close": [101.0, 101.1, 101.2, 101.3, 101.4, 101.5, 101.6, 101.7],
                "volume": [10, 11, 12, 13, 12, 14, 15, 16],
            }),
            "5m": pd.DataFrame({
                "timestamp": pd.date_range("2024-01-01 00:00:00", periods=6, freq="5min"),
                "open": [100.8, 100.9, 101.0, 101.2, 101.3, 101.4],
                "high": [101.1, 101.2, 101.3, 101.4, 101.5, 101.6],
                "low": [100.6, 100.7, 100.8, 101.0, 101.1, 101.2],
                "close": [100.9, 101.0, 101.1, 101.2, 101.3, 101.4],
                "volume": [20, 22, 24, 23, 25, 26],
            }),
        }
        candles = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01 00:00:00", periods=8, freq="min"),
            "open": [101.1, 101.2, 101.3, 101.4, 101.5, 101.6, 101.7, 101.8],
            "high": [101.4, 101.5, 101.6, 101.7, 101.8, 101.9, 102.0, 102.1],
            "low": [100.9, 101.0, 101.1, 101.2, 101.3, 101.4, 101.5, 101.6],
            "close": [101.2, 101.3, 101.4, 101.5, 101.6, 101.7, 101.8, 101.9],
            "volume": [10, 11, 12, 13, 12, 14, 15, 16],
        })

        signal = build_signal_from_recent_candles(strategy, candles, timeframe="1m", macro_context=macro_context)
        self.assertIsNone(signal)

    def test_should_emit_signal_respects_cooldown(self):
        signal = {
            "strategy_id": "nas100_ob_choch_v1",
            "direction": "bullish",
            "entry_price": 100.0,
            "stop_price": 99.0,
            "target_price": 103.0,
            "position_size": 0.5,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        last_signal_time = datetime.now(timezone.utc) - timedelta(minutes=5)

        self.assertFalse(should_emit_signal(signal, last_signal_time, cooldown_minutes=15))
        self.assertTrue(should_emit_signal(signal, last_signal_time - timedelta(minutes=30), cooldown_minutes=15))

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
