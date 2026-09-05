from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from strategy.portfolio import scheduler_lock


class SchedulerLockTests(unittest.TestCase):
    def test_dead_owner_lock_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "scheduler.lock"
            lock_path.write_text("99999999", encoding="ascii")

            with patch("strategy.portfolio._pid_is_running", return_value=False):
                with scheduler_lock(lock_path):
                    self.assertEqual(
                        lock_path.read_text(encoding="ascii"), str(os.getpid())
                    )

            self.assertFalse(lock_path.exists())

    def test_live_owner_lock_still_blocks_duplicate_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "scheduler.lock"
            lock_path.write_text("12345", encoding="ascii")

            with patch("strategy.portfolio._pid_is_running", return_value=True):
                with self.assertRaisesRegex(RuntimeError, r"PID 12345"):
                    with scheduler_lock(lock_path):
                        self.fail("살아 있는 PID의 잠금을 획득하면 안 됩니다.")

            self.assertEqual(lock_path.read_text(encoding="ascii"), "12345")


if __name__ == "__main__":
    unittest.main()
