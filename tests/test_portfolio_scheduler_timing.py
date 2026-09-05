from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from strategy.portfolio import market_cycle, next_monthly_check


class SchedulerTimingTests(unittest.TestCase):
    @patch("strategy.portfolio.next_market_open")
    def test_incomplete_current_cycle_uses_next_market_open(
        self, next_market_open
    ) -> None:
        now = pd.Timestamp("2026-09-05T00:00:00Z")
        expected = pd.Timestamp("2026-09-08T00:00:00Z")
        next_market_open.return_value = expected

        self.assertEqual(next_monthly_check("KR", "2026-08", now), expected)
        next_market_open.assert_called_once_with("KR", now)

    @patch("strategy.portfolio.xcals.get_calendar")
    def test_completed_december_cycle_rolls_to_next_year(self, get_calendar) -> None:
        now = pd.Timestamp("2026-12-15T12:00:00Z")
        calendar = MagicMock()
        session = pd.Timestamp("2027-01-04")
        expected = pd.Timestamp("2027-01-04T14:30:00Z")
        calendar.date_to_session.return_value = session
        calendar.session_open.return_value = expected
        get_calendar.return_value = calendar

        self.assertEqual(next_monthly_check("US", "2026-12", now), expected)
        calendar.date_to_session.assert_called_once_with(
            pd.Timestamp(date(2027, 1, 1)), direction="next"
        )
        calendar.session_open.assert_called_once_with(session)

    def test_market_cycle_uses_each_market_local_month(self) -> None:
        moment = pd.Timestamp("2026-09-01T02:00:00Z")

        self.assertEqual(market_cycle("KR", moment), "2026-09")
        self.assertEqual(market_cycle("US", moment), "2026-08")


if __name__ == "__main__":
    unittest.main()
