import importlib.util
import unittest
from unittest.mock import MagicMock, patch

import live.capital_live as capital_live

MODULE_PATH = "/workspaces/ai-trading-floor/scripts/fetch_data_capitalcom.py"

spec = importlib.util.spec_from_file_location("capital_fetch", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CapitalEpicResolutionTests(unittest.TestCase):
    def test_build_epic_candidates_for_us100(self):
        candidates = module.build_epic_candidates("US100")
        self.assertIn("US100", candidates)
        self.assertIn("NAS100", candidates)
        self.assertEqual(candidates[0], "US100")

    def test_resolve_epic_uses_market_results(self):
        def fake_search(_api_key, _cst, _token, term):
            if term == "US100":
                return [{"epic": "NAS100", "instrumentName": "NASDAQ 100"}]
            return []

        self.assertEqual(
            module.resolve_epic_aliases("key", "cst", "token", "US100", fake_search),
            "NAS100",
        )

    @patch("scripts.fetch_data_capitalcom.requests.put")
    @patch("scripts.fetch_data_capitalcom.requests.post")
    def test_create_session_retries_on_429(self, mock_post, mock_put):
        first_response = MagicMock(status_code=429, text='{"errorCode":"error.too-many.requests"}')
        second_response = MagicMock(
            status_code=200,
            headers={"CST": "abc123", "X-SECURITY-TOKEN": "token123"},
            json=lambda: {"accounts": [{"accountId": 42, "preferred": True}]},
        )
        mock_post.side_effect = [first_response, second_response]
        mock_put.return_value = MagicMock(status_code=200, headers={"CST": "abc123", "X-SECURITY-TOKEN": "token123"})

        with patch("scripts.fetch_data_capitalcom.time.sleep") as mock_sleep:
            session = module.create_session("key", "identifier", "password")

        self.assertEqual(session["cst"], "abc123")
        self.assertEqual(session["security_token"], "token123")
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once_with(2)

    @patch("live.capital_live.create_session")
    @patch("live.capital_live.requests.get")
    @patch("live.capital_live._load_env_and_validate")
    def test_fetch_recent_candles_reuses_cached_session(self, mock_env, mock_get, mock_create_session):
        capital_live.invalidate_session_cache()
        mock_env.return_value = {"api_key": "key", "identifier": "id", "password": "pass"}
        mock_create_session.return_value = {"cst": "abc", "security_token": "token"}

        payload = {
            "prices": [
                {
                    "snapshotTimeUTC": "2024-01-01T00:00:00Z",
                    "openPrice": {"bid": 100.0},
                    "highPrice": {"bid": 101.0},
                    "lowPrice": {"bid": 99.0},
                    "closePrice": {"bid": 100.5},
                    "lastTradedVolume": 10,
                },
                {
                    "snapshotTimeUTC": "2024-01-01T00:05:00Z",
                    "openPrice": {"bid": 101.0},
                    "highPrice": {"bid": 102.0},
                    "lowPrice": {"bid": 100.0},
                    "closePrice": {"bid": 101.5},
                    "lastTradedVolume": 11,
                },
            ]
        }
        mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)

        first = capital_live.fetch_recent_candles("US100", "MINUTE_5", hours=1, max_points=10)
        second = capital_live.fetch_recent_candles("US100", "MINUTE_5", hours=1, max_points=10)

        self.assertEqual(mock_create_session.call_count, 1)
        self.assertEqual(len(first["df"]), 2)
        self.assertEqual(len(second["df"]), 2)
        capital_live.invalidate_session_cache()


if __name__ == "__main__":
    unittest.main()
