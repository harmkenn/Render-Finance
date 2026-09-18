import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

import main


class GetDefaultPageTests(unittest.TestCase):
    def test_premarket_before_open(self):
        fake_now = datetime(2026, 9, 18, 8, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(main.get_default_page_for(fake_now), "Premarket Movers")

    def test_post_market_open_uses_daily_gainers(self):
        fake_now = datetime(2026, 9, 18, 9, 45, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(main.get_default_page_for(fake_now), "Top Daily Gainers")

    def test_after_hours_uses_daily_gainers(self):
        fake_now = datetime(2026, 9, 18, 23, 0, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(main.get_default_page_for(fake_now), "Top Daily Gainers")

    def test_intraday_sidebar_refresh_clears_cache(self):
        with patch("main.clear_caches") as clear_mock, patch("main.render_sidebar_range", return_value=["updated"]) as render_mock:
            result = main.update_intraday_sidebar("intraday", "TQQQ, UPRO", 3, "TQQQ")
        clear_mock.assert_called_once()
        render_mock.assert_called_once_with(["TQQQ", "UPRO"])
        self.assertEqual(result, ["updated"])


if __name__ == "__main__":
    unittest.main()
