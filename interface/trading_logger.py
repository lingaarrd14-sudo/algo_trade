"""
JSONL logger for trading events.

This module intentionally keeps broker secrets out of logs. Access tokens,
app secrets, authorization headers, and account-like values are redacted or
masked before being written.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

SENSITIVE_KEYWORDS = (
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "appsecret",
    "app_secret",
    "secret",
    "password",
    "passwd",
    "pwd",
)

ACCOUNT_KEYWORDS = (
    "cano",
    "account",
    "account_no",
    "acct",
)


def log_token_issued(
    *,
    provider: str = "kis",
    env_name: str | None = None,
    expires_in: int | None = None,
    expires_at: str | None = None,
    token: str | None = None,
    response: dict[str, Any] | None = None,
    log_dir: Path | str | None = None,
) -> Path:
    """Log a successful token issuance without storing the raw token."""
    payload: dict[str, Any] = {
        "provider": provider,
        "env_name": env_name,
        "expires_in": expires_in,
        "expires_at": expires_at,
        "token_hash_prefix": _hash_prefix(token),
        "response": response,
    }
    return log_event("TOKEN_ISSUED", payload, category="auth", log_dir=log_dir)


def log_token_failed(
    *,
    provider: str = "kis",
    env_name: str | None = None,
    status_code: int | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    response: dict[str, Any] | str | None = None,
    log_dir: Path | str | None = None,
) -> Path:
    """Log a failed token issuance attempt."""
    payload = {
        "provider": provider,
        "env_name": env_name,
        "status_code": status_code,
        "error_code": error_code,
        "error_message": error_message,
        "response": response,
    }
    return log_event("TOKEN_ISSUE_FAILED", payload, category="auth", log_dir=log_dir)


def log_order_requested(
    *,
    market: str,
    side: str,
    symbol: str,
    quantity: int | float | str,
    price: int | float | str | None = None,
    order_kind: str | None = None,
    tr_id: str | None = None,
    endpoint: str | None = None,
    request_body: dict[str, Any] | None = None,
    strategy: str | None = None,
    log_dir: Path | str | None = None,
) -> Path:
    """Log the intent to place an order before calling the broker API."""
    payload = {
        "market": market,
        "side": side,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "order_kind": order_kind,
        "tr_id": tr_id,
        "endpoint": endpoint,
        "request_body": request_body,
        "strategy": strategy,
    }
    return log_event("ORDER_REQUESTED", payload, category="orders", log_dir=log_dir)


def log_order_result(
    *,
    market: str,
    side: str,
    symbol: str,
    quantity: int | float | str,
    price: int | float | str | None = None,
    response: dict[str, Any] | None = None,
    tr_id: str | None = None,
    endpoint: str | None = None,
    strategy: str | None = None,
    log_dir: Path | str | None = None,
) -> Path:
    """Log the broker response after an order request."""
    success = _is_kis_success(response)
    payload = {
        "market": market,
        "side": side,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "success": success,
        "tr_id": tr_id,
        "endpoint": endpoint,
        "strategy": strategy,
        "order_no": _extract_order_no(response),
        "message_code": _get_first(response, "msg_cd", "msg_code"),
        "message": _get_first(response, "msg1", "msg"),
        "response": response,
    }
    event = "ORDER_ACCEPTED" if success else "ORDER_REJECTED"
    return log_event(event, payload, category="orders", log_dir=log_dir)


def log_order_exception(
    *,
    market: str,
    side: str,
    symbol: str,
    quantity: int | float | str,
    price: int | float | str | None = None,
    error: BaseException,
    tr_id: str | None = None,
    endpoint: str | None = None,
    strategy: str | None = None,
    log_dir: Path | str | None = None,
) -> Path:
    """Log an exception raised while placing an order."""
    payload = {
        "market": market,
        "side": side,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "success": False,
        "tr_id": tr_id,
        "endpoint": endpoint,
        "strategy": strategy,
        "error_type": type(error).__name__,
        "error_message": str(error),
    }
    return log_event("ORDER_EXCEPTION", payload, category="orders", log_dir=log_dir)


def log_event(
    event: str,
    payload: dict[str, Any] | None = None,
    *,
    category: str = "events",
    log_dir: Path | str | None = None,
) -> Path:
    """Append one sanitized JSON object to a daily JSONL log file."""
    now = datetime.now().astimezone()
    target_dir = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "time": now.isoformat(timespec="seconds"),
        "event": event,
        "payload": _sanitize(payload or {}),
    }

    path = target_dir / f"{category}_{now:%Y-%m-%d}.jsonl"
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    return path


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_key_value(str(key), item) for key, item in value.items()}

    if isinstance(value, list):
        return [_sanitize(item) for item in value]

    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]

    return value


def _sanitize_key_value(key: str, value: Any) -> Any:
    normalized = key.lower()

    if any(keyword in normalized for keyword in SENSITIVE_KEYWORDS):
        return _redact_secret(value)

    if any(keyword in normalized for keyword in ACCOUNT_KEYWORDS):
        return _mask_account(value)

    return _sanitize(value)


def _redact_secret(value: Any) -> str | None:
    if value in (None, ""):
        return None

    text = str(value)
    return f"<redacted:{_hash_prefix(text) or 'empty'}>"


def _mask_account(value: Any) -> Any:
    if value in (None, ""):
        return value

    text = str(value)
    if len(text) <= 4:
        return "*" * len(text)

    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


def _hash_prefix(value: str | None, length: int = 12) -> str | None:
    if not value:
        return None

    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:length]


def _is_kis_success(response: dict[str, Any] | None) -> bool:
    if not isinstance(response, dict):
        return False

    return str(response.get("rt_cd", "")) == "0"


def _extract_order_no(response: dict[str, Any] | None) -> str | None:
    if not isinstance(response, dict):
        return None

    for section_name in ("output", "output1", "output2"):
        section = response.get(section_name)
        if isinstance(section, dict):
            order_no = _get_first(section, "ODNO", "odno", "order_no")
            if order_no:
                return str(order_no)

    order_no = _get_first(response, "ODNO", "odno", "order_no")
    return str(order_no) if order_no else None


def _get_first(data: dict[str, Any] | None, *keys: str) -> Any:
    if not isinstance(data, dict):
        return None

    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value

    return None
