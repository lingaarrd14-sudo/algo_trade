from __future__ import annotations

import unittest
from unittest.mock import call, patch

from strategy.portfolio import build_order_plan, ensure_orderable, place_orders


class PortfolioOrderFlowTests(unittest.TestCase):
    @staticmethod
    def target() -> dict:
        return {
            "fx_symbol": "FX@KRW",
            "portfolio": [
                {
                    "country": "KR",
                    "symbol": "069500",
                    "name": "KODEX 200",
                    "exchange": "KRX",
                    "weight": 0.5,
                },
                {
                    "country": "US",
                    "symbol": "IVV",
                    "name": "iShares Core S&P 500 ETF",
                    "exchange": "AMS",
                    "weight": 0.5,
                },
            ],
        }

    @patch("strategy.portfolio.current_price", side_effect=[100_000.0, 500.0])
    @patch("strategy.portfolio.current_quantities", return_value={"069500": 20, "IVV": 7})
    @patch("strategy.portfolio.current_fx", return_value=1_400.0)
    def test_plan_uses_strategy_quantity_but_preserves_account_target(
        self, current_fx, current_quantities, current_price
    ) -> None:
        managed = {
            "positions": {
                "069500": {"country": "KR", "quantity": 10},
                "IVV": {"country": "US", "quantity": 2},
            }
        }

        orders = build_order_plan(
            "token",
            self.target(),
            capital_krw=10_000_000,
            threshold=0,
            managed_portfolio=managed,
        )

        by_symbol = {order["symbol"]: order for order in orders}
        self.assertEqual(by_symbol["069500"]["quantity"], 40)
        self.assertEqual(by_symbol["069500"]["account_target_quantity"], 60)
        self.assertEqual(by_symbol["IVV"]["quantity"], 5)
        self.assertEqual(by_symbol["IVV"]["account_target_quantity"], 12)
        self.assertTrue(
            all(
                order["pricing_basis"] == "planning_quote_excludes_fees"
                for order in orders
            )
        )

    @patch("strategy.portfolio.wait_for_target_quantity")
    @patch("strategy.portfolio.ensure_orderable")
    @patch("strategy.portfolio.overseas.order_stock")
    @patch("strategy.portfolio.domestic.order_stock")
    def test_place_orders_sells_before_buys_and_records_each_transition(
        self, domestic_order, overseas_order, ensure_orderable, wait_for_target
    ) -> None:
        domestic_order.return_value = {"rt_cd": "0", "output": {"ODNO": "11"}}
        overseas_order.return_value = {"rt_cd": "0", "output": {"ODNO": "22"}}
        buy = {
            "country": "US",
            "exchange": "AMS",
            "symbol": "IVV",
            "side": "buy",
            "quantity": 1,
            "price": 500.0,
            "target_quantity": 2,
        }
        sell = {
            "country": "KR",
            "exchange": "KRX",
            "symbol": "069500",
            "side": "sell",
            "quantity": 2,
            "price": 100_000.0,
            "target_quantity": 8,
        }
        transitions: list[tuple[str, str, str]] = []

        place_orders(
            "token",
            [buy, sell],
            on_accepted=lambda order, number: transitions.append(
                ("accepted", order["symbol"], number)
            ),
            on_filled=lambda order, number: transitions.append(
                ("filled", order["symbol"], number)
            ),
        )

        self.assertEqual(
            transitions,
            [
                ("accepted", "069500", "11"),
                ("filled", "069500", "11"),
                ("accepted", "IVV", "22"),
                ("filled", "IVV", "22"),
            ],
        )
        self.assertEqual(ensure_orderable.call_args_list, [call("token", sell), call("token", buy)])
        self.assertEqual(wait_for_target.call_args_list, [call("token", sell), call("token", buy)])

    @patch("strategy.portfolio.domestic.inquire_orderable")
    def test_buy_is_blocked_when_kis_orderable_quantity_is_insufficient(
        self, inquire_orderable
    ) -> None:
        inquire_orderable.return_value = {
            "rt_cd": "0",
            "output": {"nrcvb_buy_qty": "2"},
        }
        order = {
            "country": "KR",
            "symbol": "069500",
            "side": "buy",
            "quantity": 3,
            "price": 100_000.0,
        }

        with self.assertRaisesRegex(RuntimeError, "주문 가능 수량 부족"):
            ensure_orderable("token", order)


if __name__ == "__main__":
    unittest.main()
