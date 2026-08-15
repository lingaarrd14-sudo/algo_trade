"""
주문/토큰 발급 로그를 JSONL 파일로 남기는 간단한 모듈.

로그 파일은 interface 폴더에 바로 저장됩니다.
예: interface/orders_2026-08-15.jsonl
"""

import hashlib
import json
import os
from datetime import datetime


LOG_DIR = os.path.dirname(os.path.abspath(__file__))
SENSITIVE_KEYS = {"token", "access_token", "refresh_token", "secret", "password", "authorization"}


def log_token(status, provider="kis", env_name=None, token=None, expires_in=None, message=None, response=None):
    """토큰 발급, 캐시 사용, 실패 이력을 남깁니다."""
    data = {
        "status": status,
        "provider": provider,
        "env_name": env_name,
        "token_hash": _hash_token(token),
        "expires_in": expires_in,
        "message": message,
        "response": response,
    }
    return log_event("TOKEN", data, "auth")


def log_order(
    status,
    market,
    side,
    symbol,
    quantity,
    price=None,
    order_type=None,
    response=None,
    message=None,
    strategy=None,
):
    """주문 요청, 성공, 실패, 체결 이력을 남깁니다."""
    data = {
        "status": status,
        "market": market,
        "side": side,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "order_type": order_type,
        "strategy": strategy,
        "message": message,
        "order_no": _get_order_no(response),
        "response": response,
    }
    return log_event("ORDER", data, "orders")


def log_event(event, data, filename_prefix="events"):
    """날짜별 JSONL 파일에 로그 한 줄을 추가합니다."""
    now = datetime.now().astimezone()
    record = {
        "time": now.isoformat(timespec="seconds"),
        "event": event,
        "data": _hide_sensitive(data),
    }

    filename = f"{filename_prefix}_{now:%Y-%m-%d}.jsonl"
    log_file = os.path.join(LOG_DIR, filename)

    with open(log_file, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return log_file


def _hide_sensitive(value):
    """응답 데이터 안의 토큰/비밀번호 같은 값을 숨깁니다."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in SENSITIVE_KEYS:
                result[key] = "<hidden>"
            else:
                result[key] = _hide_sensitive(item)
        return result

    if isinstance(value, list):
        return [_hide_sensitive(item) for item in value]

    return value


def _hash_token(token):
    """토큰 원문 대신 짧은 해시만 저장합니다."""
    if not token:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


def _get_order_no(response):
    """KIS 주문 응답에서 주문번호를 꺼냅니다."""
    if not isinstance(response, dict):
        return None

    output = response.get("output")
    if isinstance(output, dict):
        return output.get("ODNO") or output.get("odno")

    return response.get("ODNO") or response.get("odno")
