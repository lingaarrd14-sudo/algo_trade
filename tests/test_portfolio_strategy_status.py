from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from strategy.portfolio import (
    managed_portfolio_snapshot,
    print_managed_portfolio_status,
    strategy_cost_basis_by_symbol,
)


class StrategyStatusTests(unittest.TestCase):
    @staticmethod
    def write_records(path: Path, records: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_additional_orders_join_existing_position_cost_basis(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            execution_path = Path(directory) / "executions.jsonl"
            self.write_records(
                execution_path,
                [
                    {
                        "event": "legacy_reconciled",
                        "orders": [
                            {
                                "symbol": "069500",
                                "side": "buy",
                                "filled_quantity": 2,
                                "purchase_amount_krw": 200_000,
                            }
                        ],
                    },
                    {
                        "event": "order_filled",
                        "order_no": "2",
                        "order": {
                            "symbol": "069500",
                            "side": "buy",
                            "quantity": 1,
                            "unit_value_krw": 120_000,
                        },
                    },
                    {
                        "event": "order_filled",
                        "order_no": "3",
                        "order": {
                            "symbol": "069500",
                            "side": "sell",
                            "quantity": 1,
                            "unit_value_krw": 130_000,
                        },
                    },
                ],
            )
            managed = {"positions": {"069500": {"quantity": 2}}}

            costs = strategy_cost_basis_by_symbol(execution_path, managed)

            # 20만원 + 추가매수 12만원에서 1/3 매도 후 남은 이동평균 원가다.
            self.assertAlmostEqual(costs["069500"], 320_000 * 2 / 3)

    @patch("strategy.portfolio.current_price", return_value=120_000)
    @patch("strategy.portfolio.current_quantities", return_value={"069500": 2})
    def test_snapshot_uses_only_strategy_quantity(
        self, current_quantities, current_price
    ) -> None:
        managed = {
            "estimated_cash_krw": 100_000,
            "positions": {
                "069500": {
                    "symbol": "069500",
                    "name": "KODEX 200",
                    "country": "KR",
                    "exchange": "KRX",
                    "quantity": 2,
                }
            },
        }

        snapshot = managed_portfolio_snapshot(
            "token", {"fx_symbol": "FX@KRW"}, managed
        )

        self.assertEqual(snapshot["positions"][0]["quantity"], 2)
        self.assertEqual(snapshot["holdings_value_krw"], 240_000)
        self.assertEqual(snapshot["total_value_krw"], 340_000)

    @patch("strategy.portfolio.current_price", return_value=120_000)
    @patch("strategy.portfolio.current_quantities", return_value={"069500": 2})
    def test_status_prints_quantity_value_and_return(
        self, current_quantities, current_price
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            execution_path = Path(directory) / "executions.jsonl"
            self.write_records(
                execution_path,
                [
                    {
                        "event": "legacy_reconciled",
                        "orders": [
                            {
                                "symbol": "069500",
                                "side": "buy",
                                "filled_quantity": 2,
                                "purchase_amount_krw": 200_000,
                            }
                        ],
                    }
                ],
            )
            managed = {
                "estimated_cash_krw": 100_000,
                "positions": {
                    "069500": {
                        "symbol": "069500",
                        "name": "KODEX 200",
                        "country": "KR",
                        "exchange": "KRX",
                        "quantity": 2,
                    }
                },
            }
            output = io.StringIO()

            with redirect_stdout(output):
                print_managed_portfolio_status(
                    "token",
                    {"fx_symbol": "FX@KRW"},
                    managed,
                    execution_path,
                    title="복구 후 포트폴리오 전략 보유현황",
                )

            text = output.getvalue()
            self.assertIn("복구 후 포트폴리오 전략 보유현황", text)
            self.assertIn("2주", text)
            self.assertIn("평가 240,000원", text)
            self.assertIn("+20.00%", text)

    def test_cost_is_hidden_when_log_quantity_does_not_match_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            execution_path = Path(directory) / "executions.jsonl"
            self.write_records(
                execution_path,
                [
                    {
                        "event": "legacy_reconciled",
                        "orders": [
                            {
                                "symbol": "069500",
                                "side": "buy",
                                "filled_quantity": 1,
                                "purchase_amount_krw": 100_000,
                            }
                        ],
                    }
                ],
            )
            managed = {"positions": {"069500": {"quantity": 2}}}

            self.assertEqual(strategy_cost_basis_by_symbol(execution_path, managed), {})

    def test_duplicate_fill_event_with_same_execution_id_is_counted_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            execution_path = Path(directory) / "executions.jsonl"
            event = {
                "event": "order_filled",
                "execution_id": "stable-order-id",
                "order_no": "11",
                "order": {
                    "symbol": "069500",
                    "side": "buy",
                    "quantity": 1,
                    "unit_value_krw": 100_000,
                },
            }
            self.write_records(execution_path, [event, dict(event)])
            managed = {"positions": {"069500": {"quantity": 1}}}

            self.assertEqual(
                strategy_cost_basis_by_symbol(execution_path, managed),
                {"069500": 100_000},
            )


if __name__ == "__main__":
    unittest.main()
