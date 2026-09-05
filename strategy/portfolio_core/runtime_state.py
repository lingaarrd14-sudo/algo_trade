"""포트폴리오 실행 설정, 스케줄 상태, 장부, 실행 이력을 분리 저장한다."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from strategy.portfolio_core.ledger import (
    new_managed_portfolio,
    validate_managed_portfolio,
)


CONFIG_SCHEMA_VERSION = 1
SCHEDULER_SCHEMA_VERSION = 1
STRATEGY_ID = "portfolio"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def account_hash(account_no: str, product_code: str) -> str:
    account = f"{account_no}:{product_code}"
    return hashlib.sha256(account.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class RuntimePaths:
    directory: Path
    config: Path
    scheduler: Path
    ledger: Path
    executions: Path
    lock: Path
    legacy_backup: Path


def runtime_paths(
    runtime_root: Path,
    environment: str,
    account_digest: str,
    strategy_id: str = STRATEGY_ID,
) -> RuntimePaths:
    safe_environment = environment.lower().strip()
    directory = runtime_root / f"{safe_environment}-{account_digest}-{strategy_id}"
    return RuntimePaths(
        directory=directory,
        config=directory / "config.json",
        scheduler=directory / "scheduler.json",
        ledger=directory / "ledger.json",
        executions=directory / "executions.jsonl",
        lock=directory / "scheduler.lock",
        legacy_backup=directory / "legacy_scheduler_state.json",
    )


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"상태 파일 형식이 잘못됐습니다: {path}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


class RuntimeStore:
    """한 환경·계좌·전략에 속하는 런타임 파일을 일관되게 관리한다."""

    def __init__(
        self,
        runtime_root: Path,
        environment: str,
        account_no: str,
        product_code: str,
        initial_capital_krw: int,
        *,
        strategy_id: str = STRATEGY_ID,
    ) -> None:
        self.runtime_root = runtime_root
        self.environment = environment.lower().strip()
        if self.environment not in {"paper", "real"}:
            raise ValueError("KIS 환경은 paper 또는 real이어야 합니다.")
        self.account_digest = account_hash(account_no or "", product_code)
        self.initial_capital_krw = int(initial_capital_krw)
        if self.initial_capital_krw <= 0:
            raise ValueError("최초 투자금은 0보다 커야 합니다.")
        self.strategy_id = strategy_id
        self.paths = runtime_paths(
            runtime_root, self.environment, self.account_digest, strategy_id
        )

    def _new_config(self) -> dict:
        return {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "environment": self.environment,
            "account_hash": self.account_digest,
            "initial_capital_krw": self.initial_capital_krw,
            "created_at": utc_iso(),
        }

    @staticmethod
    def _new_scheduler() -> dict:
        return {
            "schema_version": SCHEDULER_SCHEMA_VERSION,
            "completed_cycles": {},
            "in_progress": {},
            "analysis_quarter": None,
        }

    def _validate_config(self, config: dict) -> None:
        expected = {
            "schema_version": CONFIG_SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "environment": self.environment,
            "account_hash": self.account_digest,
            "initial_capital_krw": self.initial_capital_krw,
        }
        mismatches = [key for key, value in expected.items() if config.get(key) != value]
        if mismatches:
            raise RuntimeError(
                "현재 계좌·환경·최초 투자금이 저장된 전략 설정과 다릅니다: "
                + ", ".join(mismatches)
            )

    def _migrate_legacy(self, legacy_path: Path) -> tuple[dict, dict, dict]:
        legacy = _read_json(legacy_path)
        self.paths.directory.mkdir(parents=True, exist_ok=True)
        if not self.paths.legacy_backup.exists():
            shutil.copy2(legacy_path, self.paths.legacy_backup)

        config = self._new_config()
        config["migrated_from"] = str(legacy_path)
        scheduler = self._new_scheduler()
        for key in ("completed_cycles", "in_progress", "analysis_quarter"):
            if key in legacy:
                scheduler[key] = legacy[key]
        ledger = new_managed_portfolio(
            self.initial_capital_krw, requires_reconciliation=True
        )
        self.save_config(config)
        self.save_scheduler(scheduler)
        self.save_ledger(ledger)
        self.append_execution(
            "legacy_migrated",
            {
                "legacy_path": str(legacy_path),
                "requires_reconciliation": True,
            },
        )
        return config, scheduler, ledger

    def load_or_initialize(self, legacy_path: Path | None = None) -> tuple[dict, dict, dict]:
        files_exist = any(
            path.exists()
            for path in (self.paths.config, self.paths.scheduler, self.paths.ledger)
        )
        if not files_exist:
            legacy_was_migrated = any(
                self.runtime_root.glob("*/legacy_scheduler_state.json")
            )
            if (
                legacy_path is not None
                and legacy_path.exists()
                and not legacy_was_migrated
            ):
                return self._migrate_legacy(legacy_path)
            config = self._new_config()
            scheduler = self._new_scheduler()
            ledger = new_managed_portfolio(self.initial_capital_krw)
            self.save_config(config)
            self.save_scheduler(scheduler)
            self.save_ledger(ledger)
            return config, scheduler, ledger

        missing = [
            str(path)
            for path in (self.paths.config, self.paths.scheduler, self.paths.ledger)
            if not path.exists()
        ]
        if missing:
            raise RuntimeError(
                "분리된 런타임 상태 파일 일부가 없습니다. 자동 초기화하지 않습니다: "
                + ", ".join(missing)
            )

        config = _read_json(self.paths.config)
        scheduler = _read_json(self.paths.scheduler)
        ledger = _read_json(self.paths.ledger)
        self._validate_config(config)
        if scheduler.get("schema_version") != SCHEDULER_SCHEMA_VERSION:
            raise RuntimeError("지원하지 않는 스케줄 상태 버전입니다.")
        validate_managed_portfolio(ledger, self.initial_capital_krw)
        return config, scheduler, ledger

    def save_config(self, config: dict) -> None:
        _write_json(self.paths.config, config)

    def save_scheduler(self, scheduler: dict) -> None:
        _write_json(self.paths.scheduler, scheduler)

    def save_ledger(self, ledger: dict) -> None:
        _write_json(self.paths.ledger, ledger)

    def append_execution(self, event: str, details: dict) -> None:
        self.paths.directory.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": utc_iso(), "event": event, **details}
        with self.paths.executions.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
