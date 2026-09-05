from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from strategy.portfolio import (
    _matched_history_row,
    ask_interrupted_recovery,
    current_quantities,
    inquire_order_history_range,
    normalize_order_no,
    order_plan_fingerprint,
    recover_interrupted_market,
)
from strategy.portfolio_core.ledger import apply_filled_order
from strategy.portfolio_core.runtime_state import RuntimeStore


class InterruptedRecoveryTests(unittest.TestCase):
    def make_runtime(self, root: Path):
        store = RuntimeStore(
            runtime_root=root,
            environment="paper",
            account_no="12345678",
            product_code="01",
            initial_capital_krw=10_000_000,
        )
        _, state, managed = store.load_or_initialize()
        interrupted = {
            "cycle": "2026-08",
            "started_at": "2026-08-28T15:20:41.732549+00:00",
        }
        state["in_progress"]["US"] = interrupted
        store.save_scheduler(state)
        return store, state, managed, interrupted

    @staticmethod
    def order() -> dict:
        return {
            "country": "US",
            "symbol": "IVV",
            "name": "iShares Core S&P 500 ETF",
            "exchange": "AMS",
            "side": "buy",
            "quantity": 2,
            "current_quantity": 0,
            "target_quantity": 2,
            "account_current_quantity": 0,
            "account_target_quantity": 2,
            "price": 500.0,
            "unit_value_krw": 700_000.0,
        }

    def append_accepted(self, store: RuntimeStore, order: dict | None = None) -> None:
        store.append_execution(
            "order_accepted",
            {"order_no": "0000044824", "order": order or self.order()},
        )

    def test_order_number_comparison_ignores_leading_zero_padding(self) -> None:
        self.assertEqual(normalize_order_no("0000044824"), "44824")
        row = _matched_history_row(
            [{"odno": "44824", "pdno": "IVV"}],
            "0000044824",
            self.order(),
        )
        self.assertEqual(row["odno"], "44824")

    def test_decline_is_default_and_does_not_need_api(self) -> None:
        approved = ask_interrupted_recovery(
            "US",
            {"cycle": "2026-08"},
            Path("scheduler.json"),
            reader=lambda _: "",
        )
        self.assertFalse(approved)

    def test_fully_filled_order_updates_ledger_once_and_clears_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            self.append_accepted(store)
            history = [
                {
                    "odno": "44824",
                    "pdno": "IVV",
                    "ft_ord_qty": "2",
                    "ft_ccld_qty": "2",
                    "nccs_qty": "0",
                }
            ]

            with (
                patch(
                    "strategy.portfolio.inquire_order_history_range",
                    return_value=history,
                ),
                patch("strategy.portfolio.current_quantities", return_value={"IVV": 2}),
            ):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertNotIn("US", state["in_progress"])
            self.assertEqual(managed["positions"]["IVV"]["quantity"], 2)
            self.assertEqual(managed["estimated_cash_krw"], 8_600_000)
            saved = json.loads(store.paths.scheduler.read_text(encoding="utf-8"))
            self.assertNotIn("US", saved["in_progress"])
            self.assertIn(
                '"event": "order_filled_recovered"',
                store.paths.executions.read_text(encoding="utf-8"),
            )

    def test_already_saved_fill_is_not_applied_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            order = self.order()
            self.append_accepted(store, order)
            apply_filled_order(managed, order)
            store.save_ledger(managed)
            cash_after_first_apply = managed["estimated_cash_krw"]
            history = [
                {
                    "odno": "0000044824",
                    "pdno": "IVV",
                    "ft_ord_qty": "2",
                    "ft_ccld_qty": "2",
                    "nccs_qty": "0",
                }
            ]

            with (
                patch(
                    "strategy.portfolio.inquire_order_history_range",
                    return_value=history,
                ),
                patch("strategy.portfolio.current_quantities", return_value={"IVV": 2}),
            ):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertEqual(managed["estimated_cash_krw"], cash_after_first_apply)

    def test_open_or_partial_order_keeps_runtime_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            self.append_accepted(store)
            scheduler_before = store.paths.scheduler.read_text(encoding="utf-8")
            ledger_before = store.paths.ledger.read_text(encoding="utf-8")
            history = [
                {
                    "odno": "0000044824",
                    "pdno": "IVV",
                    "ft_ord_qty": "2",
                    "ft_ccld_qty": "1",
                    "nccs_qty": "1",
                }
            ]

            with (
                patch(
                    "strategy.portfolio.inquire_order_history_range",
                    return_value=history,
                ),
                patch("strategy.portfolio.current_quantities", return_value={"IVV": 1}),
                self.assertRaisesRegex(RuntimeError, "부분체결 또는 미체결"),
            ):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertEqual(
                store.paths.scheduler.read_text(encoding="utf-8"), scheduler_before
            )
            self.assertEqual(store.paths.ledger.read_text(encoding="utf-8"), ledger_before)
            self.assertIn("US", state["in_progress"])

    def test_filled_order_with_balance_mismatch_keeps_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            self.append_accepted(store)
            scheduler_before = store.paths.scheduler.read_text(encoding="utf-8")
            history = [
                {
                    "odno": "0000044824",
                    "pdno": "IVV",
                    "ft_ord_qty": "2",
                    "ft_ccld_qty": "2",
                    "nccs_qty": "0",
                }
            ]

            with (
                patch(
                    "strategy.portfolio.inquire_order_history_range",
                    return_value=history,
                ),
                patch("strategy.portfolio.current_quantities", return_value={"IVV": 1}),
                self.assertRaisesRegex(RuntimeError, "실제 잔고가 체결 목표와 다릅니다"),
            ):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertEqual(
                store.paths.scheduler.read_text(encoding="utf-8"), scheduler_before
            )
            self.assertIn("US", state["in_progress"])

    def test_terminal_unfilled_order_clears_marker_only_when_balance_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            self.append_accepted(store)
            history = [
                {
                    "odno": "0000044824",
                    "pdno": "IVV",
                    "ft_ord_qty": "2",
                    "ft_ccld_qty": "0",
                    "nccs_qty": "0",
                }
            ]

            with (
                patch(
                    "strategy.portfolio.inquire_order_history_range",
                    return_value=history,
                ),
                patch("strategy.portfolio.current_quantities", return_value={}),
            ):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertNotIn("US", state["in_progress"])
            self.assertEqual(managed["positions"], {})
            self.assertEqual(managed["estimated_cash_krw"], 10_000_000)

    def test_missing_accepted_log_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            store.paths.executions.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "접수 주문 로그가 없습니다"):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertIn("US", state["in_progress"])

    def test_verified_empty_plan_can_clear_interrupted_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            interrupted["planned_orders"] = []
            interrupted["plan_fingerprint"] = order_plan_fingerprint([])
            store.save_scheduler(state)

            recover_interrupted_market(
                "token", "US", interrupted, state, managed, store
            )

            self.assertNotIn("US", state["in_progress"])
            self.assertEqual(managed["positions"], {})

    def test_modified_saved_plan_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            interrupted["planned_orders"] = [self.order()]
            interrupted["plan_fingerprint"] = order_plan_fingerprint(
                interrupted["planned_orders"]
            )
            interrupted["planned_orders"][0]["quantity"] = 3
            store.save_scheduler(state)
            scheduler_before = store.paths.scheduler.read_text(encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "손상되거나 변경"):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertEqual(
                store.paths.scheduler.read_text(encoding="utf-8"), scheduler_before
            )
            self.assertIn("US", state["in_progress"])

    def test_accepted_order_must_match_saved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, state, managed, interrupted = self.make_runtime(Path(directory))
            planned = self.order()
            interrupted["planned_orders"] = [planned]
            interrupted["plan_fingerprint"] = order_plan_fingerprint([planned])
            store.save_scheduler(state)
            accepted = {**planned, "quantity": 3, "target_quantity": 3}
            self.append_accepted(store, accepted)

            with self.assertRaisesRegex(RuntimeError, "주문 계획과 다릅니다"):
                recover_interrupted_market(
                    "token", "US", interrupted, state, managed, store
                )

            self.assertIn("US", state["in_progress"])

    @patch("strategy.portfolio.kis_client.get_all_pages")
    @patch("strategy.portfolio.kis_config.is_paper", return_value=True)
    def test_paper_order_history_uses_blank_all_filters(
        self, is_paper, get_all_pages
    ) -> None:
        get_all_pages.return_value = {"rt_cd": "0", "output": []}

        inquire_order_history_range("token", "US", "20260828", "20260902")

        params = get_all_pages.call_args.kwargs["params"]
        self.assertEqual(params["PDNO"], "")
        self.assertEqual(params["OVRS_EXCG_CD"], "")

    @patch("strategy.portfolio.kis_client.get_all_pages")
    @patch("strategy.portfolio.kis_config.is_paper", return_value=False)
    def test_real_order_history_uses_percent_all_filters(
        self, is_paper, get_all_pages
    ) -> None:
        get_all_pages.return_value = {"rt_cd": "0", "output": []}

        inquire_order_history_range("token", "US", "20260828", "20260902")

        params = get_all_pages.call_args.kwargs["params"]
        self.assertEqual(params["PDNO"], "%")
        self.assertEqual(params["OVRS_EXCG_CD"], "%")

    @patch("strategy.portfolio.overseas.inquire_balance")
    def test_identical_overseas_balance_rows_are_counted_once(self, inquire_balance) -> None:
        row = {
            "ovrs_pdno": "IVV",
            "ovrs_cblc_qty": "2",
            "ovrs_excg_cd": "AMEX",
            "avg_unpr3": "500.0",
        }
        inquire_balance.return_value = {
            "rt_cd": "0",
            "output1": [
                dict(row),
                dict(row),
                {**row, "ovrs_cblc_qty": "1", "avg_unpr3": "501.0"},
            ],
        }

        # 완전히 동일한 행만 제거하며 다른 원본 행을 티커만으로 합치지 않는다.
        self.assertEqual(current_quantities("token", {"US"}), {"IVV": 3})


if __name__ == "__main__":
    unittest.main()
