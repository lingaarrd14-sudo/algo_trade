from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from strategy.portfolio_core.ledger import (
    apply_filled_order,
    require_reconciled,
)
from strategy.portfolio_core.runtime_state import RuntimeStore


class RuntimeStoreTests(unittest.TestCase):
    def test_non_positive_capital_is_rejected_before_state_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "0보다 커야"):
                RuntimeStore(
                    runtime_root=root,
                    environment="paper",
                    account_no="12345678",
                    product_code="01",
                    initial_capital_krw=0,
                )
            self.assertEqual(list(root.iterdir()), [])

    def make_store(
        self,
        root: Path,
        capital: int = 10_000_000,
        account_no: str = "12345678",
    ) -> RuntimeStore:
        return RuntimeStore(
            runtime_root=root,
            environment="paper",
            account_no=account_no,
            product_code="01",
            initial_capital_krw=capital,
        )

    def test_new_store_separates_config_scheduler_and_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            config, scheduler, ledger = store.load_or_initialize()

            self.assertTrue(store.paths.config.exists())
            self.assertTrue(store.paths.scheduler.exists())
            self.assertTrue(store.paths.ledger.exists())
            self.assertEqual(config["environment"], "paper")
            self.assertEqual(scheduler["completed_cycles"], {})
            self.assertFalse(ledger["requires_reconciliation"])

    def test_legacy_migration_preserves_cycles_and_blocks_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "scheduler_state.json"
            legacy.write_text(
                json.dumps(
                    {
                        "completed_cycles": {"KR": "2026-08"},
                        "in_progress": {},
                        "analysis_quarter": "2026-Q3",
                    }
                ),
                encoding="utf-8",
            )
            store = self.make_store(root)
            _, scheduler, ledger = store.load_or_initialize(legacy)

            self.assertEqual(scheduler["completed_cycles"]["KR"], "2026-08")
            self.assertTrue(store.paths.legacy_backup.exists())
            self.assertTrue(ledger["requires_reconciliation"])
            with self.assertRaisesRegex(RuntimeError, "실제 주문을 차단"):
                require_reconciled(ledger)

    def test_runtime_options_do_not_change_store_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self.make_store(root)
            first.load_or_initialize()
            second = self.make_store(root)
            config, _, _ = second.load_or_initialize()

            self.assertNotIn("threshold", config)
            self.assertNotIn("liquidate_unselected", config)
            self.assertEqual(first.paths.directory, second.paths.directory)

    def test_legacy_file_is_not_reused_for_another_account(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "scheduler_state.json"
            legacy.write_text(
                json.dumps({"completed_cycles": {"KR": "2026-08"}}),
                encoding="utf-8",
            )
            self.make_store(root).load_or_initialize(legacy)
            other = self.make_store(root, account_no="87654321")
            _, scheduler, ledger = other.load_or_initialize(legacy)

            self.assertEqual(scheduler["completed_cycles"], {})
            self.assertFalse(ledger["requires_reconciliation"])

    def test_capital_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_store(root).load_or_initialize()
            changed = self.make_store(root, capital=20_000_000)

            with self.assertRaisesRegex(RuntimeError, "최초 투자금"):
                changed.load_or_initialize()

    def test_filled_order_updates_only_ledger_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            _, scheduler, ledger = store.load_or_initialize()
            scheduler_before = store.paths.scheduler.read_text(encoding="utf-8")
            order = {
                "symbol": "069500",
                "name": "KODEX 200",
                "country": "KR",
                "exchange": "KRX",
                "side": "buy",
                "quantity": 2,
                "target_quantity": 2,
                "unit_value_krw": 40_000,
            }

            apply_filled_order(ledger, order)
            store.save_ledger(ledger)

            self.assertEqual(ledger["positions"]["069500"]["quantity"], 2)
            self.assertEqual(ledger["estimated_cash_krw"], 9_920_000)
            self.assertEqual(
                store.paths.scheduler.read_text(encoding="utf-8"), scheduler_before
            )


if __name__ == "__main__":
    unittest.main()
