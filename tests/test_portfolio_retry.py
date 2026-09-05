from __future__ import annotations

import unittest
from unittest.mock import patch

import requests

from strategy.portfolio import call_with_rate_limit_retry


class QueryRetryTests(unittest.TestCase):
    @patch("strategy.portfolio.time.sleep")
    def test_timeout_is_retried_for_read_only_query(self, sleep) -> None:
        responses = iter([requests.ReadTimeout("temporary"), {"rt_cd": "0"}])

        def request():
            result = next(responses)
            if isinstance(result, Exception):
                raise result
            return result

        self.assertEqual(call_with_rate_limit_retry("잔고 조회", request)["rt_cd"], "0")
        sleep.assert_called_once_with(3)

    @patch("strategy.portfolio.time.sleep")
    def test_non_rate_limit_runtime_error_is_not_retried(self, sleep) -> None:
        def request():
            raise RuntimeError("인증 실패")

        with self.assertRaisesRegex(RuntimeError, "인증 실패"):
            call_with_rate_limit_retry("잔고 조회", request)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
