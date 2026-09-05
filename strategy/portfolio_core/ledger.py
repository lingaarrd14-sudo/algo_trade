"""계좌 전체 잔고와 분리해 포트폴리오 전략 몫만 추적하는 장부."""

from __future__ import annotations

import math
from datetime import datetime, timezone


def new_managed_portfolio(
    initial_capital_krw: int, *, requires_reconciliation: bool = False
) -> dict:
    """최초 예산으로 전략 주문만 추적할 독립 장부를 만든다."""
    ledger = {
        "schema_version": 1,
        "initial_capital_krw": initial_capital_krw,
        "estimated_cash_krw": float(initial_capital_krw),
        "positions": {},
        "updated_at": None,
        "requires_reconciliation": requires_reconciliation,
    }
    if requires_reconciliation:
        ledger["reconciliation_reason"] = (
            "구버전 상태에는 전략 전용 보유수량과 추정 현금이 없습니다."
        )
    return ledger


def _number(value) -> float:
    if value in (None, ""):
        return 0.0
    return float(str(value).replace(",", ""))


def validate_managed_portfolio(managed: dict, initial_capital_krw: int) -> None:
    """저장된 전략 장부가 현재 실행 예산과 기본 형식에 맞는지 확인한다."""
    if managed.get("schema_version") != 1:
        raise RuntimeError("지원하지 않는 전략 장부 버전입니다.")
    if managed.get("initial_capital_krw") != initial_capital_krw:
        raise RuntimeError("전략 장부의 최초 예산이 현재 실행 조건과 다릅니다.")
    cash = _number(managed.get("estimated_cash_krw"))
    if not math.isfinite(cash):
        raise RuntimeError("전략 장부의 추정 현금이 올바르지 않습니다.")
    positions = managed.get("positions")
    if not isinstance(positions, dict):
        raise RuntimeError("전략 장부의 보유종목 형식이 올바르지 않습니다.")
    for symbol, position in positions.items():
        if not isinstance(position, dict) or int(_number(position.get("quantity"))) < 0:
            raise RuntimeError(f"전략 장부의 {symbol} 보유수량이 올바르지 않습니다.")


def require_reconciled(managed: dict) -> None:
    """구버전에서 장부를 복원하지 못한 상태의 실제 주문을 차단한다."""
    if managed.get("requires_reconciliation"):
        raise RuntimeError(
            "구버전 상태에서 전략 장부를 복원할 수 없어 실제 주문을 차단했습니다. "
            "기존 주문·체결과 전략 귀속 잔고를 확인한 뒤 장부를 조정해야 합니다."
        )


def apply_filled_order(managed: dict, order: dict) -> None:
    """체결이 확인된 주문 하나를 전략 수량과 추정 현금에 즉시 반영한다."""
    trade_value = float(order["quantity"]) * float(order["unit_value_krw"])
    if order["side"] == "buy":
        managed["estimated_cash_krw"] -= trade_value
    else:
        managed["estimated_cash_krw"] += trade_value

    symbol = order["symbol"]
    target_quantity = int(order["target_quantity"])
    if target_quantity == 0:
        managed["positions"].pop(symbol, None)
    else:
        managed["positions"][symbol] = {
            "symbol": symbol,
            "name": order.get("name", symbol),
            "country": order["country"],
            "exchange": order["exchange"],
            "quantity": target_quantity,
        }
    managed["updated_at"] = datetime.now(timezone.utc).isoformat()

