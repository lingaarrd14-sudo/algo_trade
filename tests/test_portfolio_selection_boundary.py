from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from strategy.dataforportfolio import main as dataforportfolio_main
from strategy.dataforportfolio import select_minimum_variance_portfolio
from strategy.portfolio import load_selected_portfolio


class PortfolioSelectionBoundaryTests(unittest.TestCase):
    def test_no_arguments_prints_startup_guide(self) -> None:
        output = io.StringIO()
        with patch("strategy.dataforportfolio.sys.argv", ["dataforportfolio.py"]):
            with redirect_stdout(output):
                dataforportfolio_main()

        guide = output.getvalue()
        self.assertIn("데이터 수집·분석 사용설명서", guide)
        self.assertIn("dataforportfolio.py run", guide)
        self.assertIn("이 파일은 주문을 보내지 않습니다", guide)

    def test_analysis_stage_selects_four_asset_target(self) -> None:
        rng = np.random.default_rng(7)
        columns = ("KR1", "KR2", "US1", "US2", "US3")
        returns = pd.DataFrame(
            rng.normal(0.001, 0.02, size=(260, len(columns))), columns=columns
        )
        universe = [
            {
                "symbol": symbol,
                "name": symbol,
                "country": "KR" if symbol.startswith("KR") else "US",
                "exchange": "KRX" if symbol.startswith("KR") else "AMS",
            }
            for symbol in columns
        ]

        selected = select_minimum_variance_portfolio(
            returns, universe, date(2026, 8, 21)
        )

        self.assertEqual(len(selected["portfolio"]), 4)
        self.assertAlmostEqual(
            sum(item["weight"] for item in selected["portfolio"]), 1.0
        )
        self.assertEqual(
            {item["country"] for item in selected["portfolio"]}, {"KR", "US"}
        )

    def test_order_stage_only_loads_persisted_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            universe = [
                {"symbol": "KR1", "name": "KR1", "country": "KR", "exchange": "KRX"},
                {"symbol": "KR2", "name": "KR2", "country": "KR", "exchange": "KRX"},
                {"symbol": "US1", "name": "US1", "country": "US", "exchange": "AMS"},
                {"symbol": "US2", "name": "US2", "country": "US", "exchange": "AMS"},
            ]
            manifest = {
                "as_of": date.today().isoformat(),
                "data_quality": "PASS",
                "universe": universe,
                "outputs": {"selected_portfolio": "selected_portfolio.json"},
            }
            selected = {
                **manifest,
                "schema_version": 1,
                "method": "minimum_variance_grid_5pct",
                "expected_return": 0.1,
                "expected_volatility": 0.2,
                "portfolio": [
                    {**item, "weight": 0.25}
                    for item in universe
                ],
            }
            manifest_path = root / "analysis_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "selected_portfolio.json").write_text(
                json.dumps(selected), encoding="utf-8"
            )

            loaded = load_selected_portfolio(manifest_path)

            self.assertEqual(loaded["portfolio"], selected["portfolio"])


if __name__ == "__main__":
    unittest.main()
