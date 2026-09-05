"""분석 단계가 확정한 포트폴리오를 읽어 KIS 주문 계획을 만든다.

기본 실행은 DRY_RUN이며 실제 주문은 ``--execute``를 명시해야 한다.
실제 주문은 매월 한국·미국 거래소의 정규장에서 시장별로 실행한다.
목표 비중은 분기 첫 점검 때 5년 데이터를 갱신해 다시 계산한다.

큰 실행 흐름:
    최종 분석 결과 검증 → 전략 묶음 평가 → 리밸런싱 주문 계획
    → 리밸런싱 주문 계획 → 주문/체결 확인 → 전략 장부 저장

    python strategy\portfolio.py --capital-krw 10000000
    python strategy\portfolio.py --capital-krw 10000000 --execute
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import exchange_calendars as xcals
import pandas as pd
import requests


# =============================================================================
# 1. 프로젝트 경로와 KIS 모듈 연결
# =============================================================================

# strategy 폴더에서 파일을 직접 실행해도 프로젝트 루트의 kis 패키지를 찾게 한다.
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from kis import kis_client, kis_config  # noqa: E402
from kis import kis_domestic as domestic  # noqa: E402
from kis import kis_overseas as overseas  # noqa: E402
from kis.kis_auth import issue_access_token  # noqa: E402
from strategy.portfolio_core.ledger import (  # noqa: E402
    apply_filled_order,
    require_reconciled,
)
from strategy.portfolio_core.runtime_state import RuntimeStore  # noqa: E402


# =============================================================================
# 2. 파일 경로, 실행 기준, 시장별 설정
# =============================================================================

# 분석 산출물과 장기 실행 상태를 서로 다른 폴더에 보관한다.
ANALYSIS_DIR = Path(__file__).parent / "portfolio_data" / "analysis"
MANIFEST_FILE = ANALYSIS_DIR / "analysis_manifest.json"
RUNTIME_ROOT = Path(__file__).parent / "portfolio_data" / "runtime"
LEGACY_SCHEDULER_STATE_FILE = RUNTIME_ROOT / "scheduler_state.json"

# 데이터 신선도, 리밸런싱 임계값, API 재시도와 체결 확인 기준이다.
MAX_SIGNAL_AGE_DAYS = 110
DEFAULT_REBALANCE_THRESHOLD = 0.03
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_WAIT_SECONDS = 3
SCHEDULER_POLL_SECONDS = 60
FILL_CHECK_SECONDS = 5
FILL_TIMEOUT_SECONDS = 120

# KIS API 코드와 국가별 거래소 캘린더/시간대 매핑이다.
FX_DAILY = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
FX_DAILY_TR = "FHKST03030100"
ORDER_EXCHANGE = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX"}
MARKET_CALENDARS = {"KR": "XKRX", "US": "XNYS"}
MARKET_TIMEZONES = {"KR": "Asia/Seoul", "US": "America/New_York"}
MARKET_NAMES = {"KR": "한국", "US": "미국"}


# =============================================================================
# 3. KIS 응답 정규화와 호출 제한 처리
# =============================================================================

def number(value) -> float:
    """쉼표가 포함된 KIS 숫자 문자열을 계산 가능한 실수로 바꾼다."""
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def as_rows(value) -> list[dict]:
    """KIS output이 dict 또는 list인 경우를 하나의 행 목록 형태로 맞춘다."""
    if isinstance(value, dict):
        return [value]
    return value if isinstance(value, list) else []


def call_with_rate_limit_retry(label: str, request) -> dict:
    """조회 중 호출 제한과 일시적 네트워크 오류만 제한적으로 재시도한다."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        retry_reason = ""
        try:
            response = request()
        except (requests.Timeout, requests.ConnectionError) as error:
            if attempt == RATE_LIMIT_RETRIES:
                raise
            retry_reason = f"일시적 네트워크 오류({type(error).__name__})"
        except RuntimeError as error:
            if "EGW00201" not in str(error) or attempt == RATE_LIMIT_RETRIES:
                raise
            retry_reason = "KIS 호출 제한"
        else:
            if str(response.get("rt_cd", "")) == "0":
                return response
            if response.get("msg_cd") != "EGW00201" or attempt == RATE_LIMIT_RETRIES:
                return response
            retry_reason = "KIS 호출 제한"

        wait_seconds = RATE_LIMIT_WAIT_SECONDS * (attempt + 1)
        print(f"{label}: {retry_reason} 때문에 {wait_seconds}초 후 재시도합니다.")
        time.sleep(wait_seconds)

    raise RuntimeError(f"{label}: 조회 재시도 횟수를 초과했습니다.")


# =============================================================================
# 4. 분석 결과 검증과 최소분산 포트폴리오 선택
# =============================================================================

def load_selected_portfolio(path: Path = MANIFEST_FILE) -> dict:
    """분석 단계가 확정해 저장한 최신 목표 포트폴리오를 검증해 읽는다."""
    if not path.exists():
        raise FileNotFoundError(
            f"분석 결과가 없습니다: {path}\n"
            "먼저 python strategy\\dataforportfolio.py run ... 을 실행하세요."
        )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("data_quality") != "PASS":
        raise ValueError("데이터 품질검사를 통과하지 않은 분석 결과입니다.")

    as_of = datetime.strptime(manifest["as_of"], "%Y-%m-%d").date()
    age = (date.today() - as_of).days
    if age < 0 or age > MAX_SIGNAL_AGE_DAYS:
        raise ValueError(f"분석 결과가 유효기간을 벗어났습니다: {as_of} ({age}일)")

    selected_name = manifest.get("outputs", {}).get("selected_portfolio")
    if not selected_name:
        raise FileNotFoundError(
            "분석 명세에 최종 포트폴리오 파일이 없습니다. "
            "python strategy\\dataforportfolio.py analyze 를 다시 실행하세요."
        )
    selected_file = path.parent / selected_name
    if not selected_file.exists():
        raise FileNotFoundError(f"최종 포트폴리오 파일이 없습니다: {selected_file}")
    selected = json.loads(selected_file.read_text(encoding="utf-8"))
    if selected.get("schema_version") != 1:
        raise ValueError("지원하지 않는 최종 포트폴리오 버전입니다.")
    if selected.get("data_quality") != "PASS" or selected.get("as_of") != manifest["as_of"]:
        raise ValueError("최종 포트폴리오와 분석 명세의 품질 또는 기준일이 다릅니다.")
    if selected.get("method") != "minimum_variance_grid_5pct":
        raise ValueError("지원하지 않는 포트폴리오 선택 방법입니다.")

    universe = {item["symbol"]: item for item in manifest.get("universe", [])}
    portfolio = selected.get("portfolio")
    if not isinstance(portfolio, list) or len(portfolio) != 4:
        raise ValueError("최종 포트폴리오는 정확히 4종목이어야 합니다.")
    symbols = [str(item.get("symbol", "")) for item in portfolio]
    if len(set(symbols)) != 4 or any(symbol not in universe for symbol in symbols):
        raise ValueError("최종 포트폴리오 종목이 중복됐거나 분석 대상에 없습니다.")
    countries = {universe[symbol]["country"] for symbol in symbols}
    if countries != {"KR", "US"}:
        raise ValueError("최종 포트폴리오에는 한국과 미국 종목이 모두 필요합니다.")
    weights = [float(item.get("weight", 0)) for item in portfolio]
    if any(not math.isfinite(weight) or not 0.10 <= weight <= 0.40 for weight in weights):
        raise ValueError("최종 포트폴리오 비중은 종목별 10~40%여야 합니다.")
    if not math.isclose(sum(weights), 1.0, abs_tol=1e-8):
        raise ValueError("최종 포트폴리오 비중 합계가 100%가 아닙니다.")
    if selected.get("universe") != manifest.get("universe"):
        raise ValueError("최종 포트폴리오와 분석 명세의 종목 정보가 다릅니다.")
    return selected


# =============================================================================
# 5. 현재 환율·가격·계좌 잔고 조회
# =============================================================================

def current_fx(token: str, symbol: str) -> float:
    """주문 수량 계산에 사용할 최신 USD/KRW 환율을 조회한다."""
    end = date.today()
    start = end - timedelta(days=10)
    response = call_with_rate_limit_retry(
        "현재 환율 조회",
        lambda: kis_client.get(
            FX_DAILY,
            FX_DAILY_TR,
            token,
            {
                "FID_COND_MRKT_DIV_CODE": "X",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": end.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
            },
        ),
    )
    if str(response.get("rt_cd", "")) != "0":
        raise RuntimeError(f"현재 환율 조회 실패: {response.get('msg1', '')}")
    quotes = [
        (str(row.get("stck_bsop_date", "")), number(row.get("ovrs_nmix_prpr")))
        for row in as_rows(response.get("output2"))
    ]
    quotes = [(quote_date, value) for quote_date, value in quotes if value > 0]
    if not quotes:
        raise RuntimeError("현재 USD/KRW 환율을 찾지 못했습니다.")
    return max(quotes, key=lambda quote: quote[0])[1]


def current_price(token: str, item: dict) -> float:
    """국내·해외 구분에 맞는 KIS API로 종목의 최신 가격을 조회한다."""
    if item["country"] == "KR":
        response = call_with_rate_limit_retry(
            f"{item['symbol']} 현재가 조회",
            lambda: domestic.inquire_price(token, item["symbol"]),
        )
        price = number(response.get("output", {}).get("stck_prpr"))
    else:
        response = call_with_rate_limit_retry(
            f"{item['symbol']} 현재가 조회",
            lambda: overseas.inquire_price(token, item["exchange"], item["symbol"]),
        )
        price = number(response.get("output", {}).get("last"))
    if str(response.get("rt_cd", "")) != "0" or price <= 0:
        raise RuntimeError(f"{item['symbol']}: 현재가 조회 실패")
    return price


def current_quantities(
    token: str, countries: set[str] | None = None
) -> dict[str, int]:
    """국내·미국 계좌의 현재 보유수량을 종목코드별로 반환한다."""
    countries = countries or {"KR", "US"}
    quantities: dict[str, int] = {}

    if "KR" in countries:
        domestic_balance = call_with_rate_limit_retry(
            "국내 잔고 조회", lambda: domestic.inquire_balance(token)
        )
        if str(domestic_balance.get("rt_cd", "")) != "0":
            raise RuntimeError(
                f"국내 잔고 조회 실패: {domestic_balance.get('msg1', '')}"
            )
        for row in as_rows(domestic_balance.get("output1")):
            symbol = str(row.get("pdno", "")).strip()
            if symbol:
                quantities[symbol] = quantities.get(symbol, 0) + int(
                    number(row.get("hldg_qty"))
                )

    if "US" in countries:
        overseas_balance = call_with_rate_limit_retry(
            "해외 잔고 조회", lambda: overseas.inquire_balance(token)
        )
        if str(overseas_balance.get("rt_cd", "")) != "0":
            raise RuntimeError(
                f"해외 잔고 조회 실패: {overseas_balance.get('msg1', '')}"
            )
        overseas_rows = overseas_balance.get(
            "output1", overseas_balance.get("output")
        )
        # 모의투자 API는 같은 보유 행을 NASD/NYSE/AMEX 조회에 반복해서
        # 돌려줄 수 있으므로 완전히 동일한 원본 행만 한 번 계산한다.
        unique_rows: list[dict] = []
        seen_rows: set[str] = set()
        for row in as_rows(overseas_rows):
            fingerprint = json.dumps(
                row, ensure_ascii=False, sort_keys=True, default=str
            )
            if fingerprint in seen_rows:
                continue
            seen_rows.add(fingerprint)
            unique_rows.append(row)

        for row in unique_rows:
            symbol = str(row.get("ovrs_pdno", row.get("pdno", ""))).strip()
            quantity = row.get("ovrs_cblc_qty", row.get("hldg_qty", 0))
            if symbol:
                quantities[symbol] = quantities.get(symbol, 0) + int(number(quantity))
    return quantities


# =============================================================================
# 6. 전략 전용 장부의 포트폴리오 평가금액
# =============================================================================

def managed_portfolio_snapshot(token: str, target: dict, managed: dict) -> dict:
    """전략 장부 보유분의 현재가·원화 평가금액을 종목별로 계산한다."""
    positions = {
        symbol: position
        for symbol, position in managed["positions"].items()
        if int(number(position.get("quantity"))) > 0
    }
    cash = number(managed["estimated_cash_krw"])
    if not positions:
        return {
            "total_value_krw": cash,
            "estimated_cash_krw": cash,
            "holdings_value_krw": 0.0,
            "positions": [],
        }

    countries = {position["country"] for position in positions.values()}
    # 같은 종목을 수동으로 매도해 전략 장부보다 실제 수량이 적으면 중단한다.
    account_quantities = current_quantities(token, countries)
    for symbol, position in positions.items():
        tracked = int(number(position["quantity"]))
        actual = account_quantities.get(symbol, 0)
        if actual < tracked:
            raise RuntimeError(
                f"{symbol} 실제 잔고가 전략 장부보다 적습니다: "
                f"실제 {actual}주, 전략 {tracked}주. 수동 거래 여부를 확인하세요."
            )

    # 미국 종목은 현재 USD/KRW 환율로 원화 환산한 뒤 국내 종목과 합산한다.
    fx = current_fx(token, target["fx_symbol"]) if "US" in countries else 1.0
    rows: list[dict] = []
    for symbol, position in positions.items():
        quantity = int(number(position["quantity"]))
        price = current_price(token, position)
        unit_krw = price if position["country"] == "KR" else price * fx
        rows.append(
            {
                **position,
                "symbol": symbol,
                "quantity": quantity,
                "current_price": price,
                "current_fx": fx if position["country"] == "US" else 1.0,
                "unit_value_krw": unit_krw,
                "market_value_krw": quantity * unit_krw,
            }
        )
    holdings_value = sum(row["market_value_krw"] for row in rows)
    return {
        "total_value_krw": cash + holdings_value,
        "estimated_cash_krw": cash,
        "holdings_value_krw": holdings_value,
        "positions": sorted(rows, key=lambda row: (row["country"], row["symbol"])),
    }


def managed_portfolio_value(
    token: str, target: dict, managed: dict
) -> tuple[float, float, float]:
    """계좌의 다른 보유분을 제외하고 전략 장부만 원화로 평가한다."""
    snapshot = managed_portfolio_snapshot(token, target, managed)
    return (
        snapshot["total_value_krw"],
        snapshot["estimated_cash_krw"],
        snapshot["holdings_value_krw"],
    )


def strategy_cost_basis_by_symbol(execution_path: Path, managed: dict) -> dict[str, float]:
    """전략 체결 로그만 재생해 현재 보유분의 이동평균 원가를 계산한다."""
    try:
        records = _execution_records(execution_path)
    except RuntimeError:
        return {}

    quantities: dict[str, int] = {}
    costs: dict[str, float] = {}
    invalid: set[str] = set()
    seen_execution_ids: set[str] = set()

    def add_buy(symbol: str, quantity: int, trade_value: float) -> None:
        if quantity <= 0 or trade_value <= 0 or not math.isfinite(trade_value):
            invalid.add(symbol)
            return
        quantities[symbol] = quantities.get(symbol, 0) + quantity
        costs[symbol] = costs.get(symbol, 0.0) + trade_value

    for record in records:
        if record.get("event") == "legacy_reconciled":
            for order in record.get("orders", []):
                if not isinstance(order, dict) or order.get("side") != "buy":
                    continue
                symbol = str(order.get("symbol", "")).strip()
                if not symbol:
                    continue
                try:
                    add_buy(
                        symbol,
                        int(number(order.get("filled_quantity"))),
                        number(order.get("purchase_amount_krw")),
                    )
                except (TypeError, ValueError):
                    invalid.add(symbol)
            continue

        if record.get("event") not in {"order_filled", "order_filled_recovered"}:
            continue
        execution_id = str(record.get("execution_id", "")).strip()
        if execution_id:
            if execution_id in seen_execution_ids:
                continue
            seen_execution_ids.add(execution_id)
        order = record.get("order")
        if not isinstance(order, dict):
            continue
        symbol = str(order.get("symbol", "")).strip()
        if not symbol:
            continue
        try:
            quantity = int(number(order.get("quantity")))
            trade_value = quantity * number(order.get("unit_value_krw"))
        except (TypeError, ValueError):
            invalid.add(symbol)
            continue
        if order.get("side") == "buy":
            add_buy(symbol, quantity, trade_value)
        elif order.get("side") == "sell":
            before = quantities.get(symbol, 0)
            if quantity <= 0 or before < quantity or before <= 0:
                invalid.add(symbol)
                continue
            remaining = before - quantity
            costs[symbol] = costs.get(symbol, 0.0) * remaining / before
            quantities[symbol] = remaining
        else:
            invalid.add(symbol)

    result: dict[str, float] = {}
    for symbol, position in managed.get("positions", {}).items():
        tracked = int(number(position.get("quantity")))
        cost = costs.get(symbol, 0.0)
        if (
            symbol not in invalid
            and tracked > 0
            and quantities.get(symbol, 0) == tracked
            and cost > 0
            and math.isfinite(cost)
        ):
            result[symbol] = cost
    return result


def print_managed_portfolio_status(
    token: str,
    target: dict,
    managed: dict,
    execution_path: Path,
    *,
    title: str = "현재 포트폴리오 전략 보유현황",
) -> tuple[float, float, float]:
    """프로그램 시작 시 전략에 귀속된 보유종목과 추정 수익률을 출력한다."""
    snapshot = managed_portfolio_snapshot(token, target, managed)
    costs = strategy_cost_basis_by_symbol(execution_path, managed)
    print(f"\n[{title}]")
    if not snapshot["positions"]:
        print("전략에 귀속된 보유종목이 없습니다.")
    known_cost = 0.0
    known_value = 0.0
    missing_cost = False
    for row in snapshot["positions"]:
        symbol = row["symbol"]
        price_text = (
            f"{row['current_price']:,.0f}원"
            if row["country"] == "KR"
            else f"${row['current_price']:,.2f}"
        )
        cost = costs.get(symbol)
        if cost is None:
            return_text = "원가 확인 불가"
            missing_cost = True
        else:
            profit = row["market_value_krw"] - cost
            return_rate = profit / cost if cost else 0.0
            return_text = f"추정 수익 {profit:+,.0f}원 ({return_rate:+.2%})"
            known_cost += cost
            known_value += row["market_value_krw"]
        print(
            f"- {symbol} {row.get('name', symbol)} | {row['quantity']}주 | "
            f"현재가 {price_text} | 평가 {row['market_value_krw']:,.0f}원 | "
            f"{return_text}"
        )

    print(
        f"보유종목 평가 {snapshot['holdings_value_krw']:,.0f}원 | "
        f"추정 현금 {snapshot['estimated_cash_krw']:,.0f}원 | "
        f"전략 합계 {snapshot['total_value_krw']:,.0f}원"
    )
    if known_cost > 0:
        total_profit = known_value - known_cost
        print(
            f"원가 확인 종목 합산 추정 수익 {total_profit:+,.0f}원 "
            f"({total_profit / known_cost:+.2%})"
        )
    if missing_cost:
        print("일부 종목은 전략 체결 로그와 장부 수량이 맞지 않아 수익률을 표시하지 않습니다.")
    elif snapshot["positions"]:
        print("수익률은 전략 장부의 추정 원가 기준이며 수수료·세금은 반영하지 않습니다.")

    return (
        snapshot["total_value_krw"],
        snapshot["estimated_cash_krw"],
        snapshot["holdings_value_krw"],
    )


# =============================================================================
# 7. 목표 비중을 실제 주문 수량으로 변환
# =============================================================================

def build_order_plan(
    token: str,
    target: dict,
    capital_krw: float,
    threshold: float,
    liquidate_unselected: bool = False,
    countries: set[str] | None = None,
    managed_portfolio: dict | None = None,
) -> list[dict]:
    """전략 평가금액과 목표 비중으로 국가별 매수·매도 계획을 만든다."""
    if capital_krw <= 0:
        raise ValueError("투자금액은 0보다 커야 합니다.")
    countries = countries or {"KR", "US"}
    fx = current_fx(token, target["fx_symbol"]) if "US" in countries else 1.0
    account_quantities = current_quantities(token, countries)
    # 전략 장부가 있으면 전체 계좌 수량이 아닌 전략에 귀속된 수량만 사용한다.
    quantities = (
        {
            symbol: int(number(position.get("quantity")))
            for symbol, position in managed_portfolio["positions"].items()
            if position.get("country") in countries
        }
        if managed_portfolio is not None
        else account_quantities
    )
    orders: list[dict] = []

    target_items = [
        item for item in target["portfolio"] if item["country"] in countries
    ]
    if liquidate_unselected:
        # 미선정 종목 정리도 전략 장부에 잡힌 수량만 대상으로 한다.
        selected = {item["symbol"] for item in target_items}
        liquidation_candidates = (
            managed_portfolio["positions"].values()
            if managed_portfolio is not None
            else target.get("universe", [])
        )
        target_items.extend(
            {**item, "weight": 0.0}
            for item in liquidation_candidates
            if item["country"] in countries
            and item["symbol"] not in selected
            and quantities.get(item["symbol"], 0) > 0
        )

    for item in target_items:
        price = current_price(token, item)
        unit_krw = price if item["country"] == "KR" else price * fx
        target_value = capital_krw * float(item["weight"])
        # 소수점 주식은 주문하지 않으므로 목표 수량은 항상 내림한다.
        target_quantity = math.floor(target_value / unit_krw)
        current_quantity = quantities.get(item["symbol"], 0)
        difference = target_quantity - current_quantity
        difference_ratio = abs(difference * unit_krw) / capital_krw
        # 작은 차이는 거래비용과 잦은 매매를 줄이기 위해 주문하지 않는다.
        if difference == 0 or difference_ratio < threshold:
            continue
        account_current_quantity = account_quantities.get(item["symbol"], 0)
        if difference < 0 and account_current_quantity < abs(difference):
            raise RuntimeError(
                f"{item['symbol']} 전략 매도수량이 실제 잔고보다 많습니다: "
                f"매도 {abs(difference)}주, 실제 {account_current_quantity}주"
            )
        orders.append(
            {
                **item,
                "side": "buy" if difference > 0 else "sell",
                "quantity": abs(difference),
                "current_quantity": current_quantity,
                "target_quantity": target_quantity,
                "account_current_quantity": account_current_quantity,
                "account_target_quantity": account_current_quantity + difference,
                "price": price,
                "unit_value_krw": unit_krw,
                "current_fx": fx,
                # 실제 체결가가 아니라 주문 계획 시점의 시세다.
                "pricing_basis": "planning_quote_excludes_fees",
            }
        )
    return orders


def order_plan_fingerprint(orders: list[dict]) -> str:
    """중단 복구 시 원래 저장한 주문 계획이 변하지 않았는지 확인한다."""
    try:
        encoded = json.dumps(
            orders,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise RuntimeError("주문 계획을 안전하게 저장할 수 없습니다.") from error
    return hashlib.sha256(encoded).hexdigest()


def order_execution_id(
    started_at: str, country: str, order_no: str, order: dict
) -> str:
    """같은 실행 주문의 체결 이벤트를 재시작 후에도 식별할 안정 키를 만든다."""
    identity = {
        "started_at": started_at,
        "country": country,
        "order_no": str(order_no).strip(),
        "order": order,
    }
    return order_plan_fingerprint([identity])


def _validated_interrupted_plan(interrupted: dict) -> list[dict] | None:
    """신규 중단 표식의 주문 계획을 검증하고, 구버전은 None으로 구분한다."""
    if "planned_orders" not in interrupted and "plan_fingerprint" not in interrupted:
        return None
    orders = interrupted.get("planned_orders")
    fingerprint = str(interrupted.get("plan_fingerprint", "")).strip()
    if not isinstance(orders, list) or any(not isinstance(order, dict) for order in orders):
        raise RuntimeError("중단 상태의 주문 계획 형식이 잘못됐습니다.")
    if not fingerprint or fingerprint != order_plan_fingerprint(orders):
        raise RuntimeError("중단 상태의 주문 계획이 손상되거나 변경됐습니다.")
    return orders


# =============================================================================
# 8. 콘솔 출력
# =============================================================================

def print_plan(orders: list[dict], execute: bool, country: str | None = None) -> None:
    """드라이런/실주문 여부와 종목별 목표 수량을 사람이 읽기 쉽게 표시한다."""
    mode = "LIVE ORDER" if execute else "DRY RUN"
    market = f" {MARKET_NAMES[country]}" if country else ""
    print(f"\n[{mode}]{market} 주문 계획")
    if not orders:
        print("리밸런싱 기준을 넘는 주문이 없습니다.")
        return
    for order in orders:
        limit_price = (
            f"  지정가 ${order['price']:.2f}" if order["country"] == "US" else ""
        )
        print(
            f"{order['side'].upper():<4} {order['symbol']:<6} "
            f"{order['quantity']:>6}주  "
            f"현재 {order['current_quantity']} → 목표 {order['target_quantity']}"
            f"{limit_price}"
        )


def print_selected_portfolio(target: dict) -> None:
    """선택된 최소분산 포트폴리오와 과거 기반 통계값을 출력한다."""
    print("\n[포트폴리오 이론 적용 결과]")
    for item in target["portfolio"]:
        print(f"{item['symbol']:<6} {item['weight']:>6.0%}  {item['country']}")
    print(f"예상 연수익률: {target['expected_return']:.2%}")
    print(f"예상 변동성  : {target['expected_volatility']:.2%}")


# =============================================================================
# 9. 주문 가능 수량 확인, 주문 전송, 체결 확인
# =============================================================================

def _orderable_quantity(response: dict, fields: tuple[str, ...]) -> int:
    """국내·해외 응답 후보 필드에서 KIS 주문 가능 수량을 꺼낸다."""
    if str(response.get("rt_cd", "")) != "0":
        raise RuntimeError(f"주문 가능 수량 조회 실패: {response.get('msg1', '')}")
    rows = as_rows(response.get("output"))
    if not rows:
        raise RuntimeError("주문 가능 수량 응답이 비어 있습니다.")
    for field in fields:
        if field in rows[0] and str(rows[0][field]).strip():
            return int(number(rows[0][field]))
    raise RuntimeError("KIS 응답에서 주문 가능 수량을 찾지 못했습니다.")


def ensure_orderable(token: str, order: dict) -> None:
    """KIS가 계산한 현금 주문 가능 수량보다 많이 사지 않도록 막는다."""
    if order["side"] != "buy":
        return
    if order["country"] == "KR":
        response = call_with_rate_limit_retry(
            f"{order['symbol']} 주문 가능 수량 조회",
            lambda: domestic.inquire_orderable(
                token, order["symbol"], order["price"]
            ),
        )
        available = _orderable_quantity(response, ("nrcvb_buy_qty", "max_buy_qty"))
    else:
        exchange = ORDER_EXCHANGE.get(order["exchange"])
        if not exchange:
            raise ValueError(f"지원하지 않는 해외 거래소: {order['exchange']}")
        response = call_with_rate_limit_retry(
            f"{order['symbol']} 주문 가능 수량 조회",
            lambda: overseas.inquire_position_amount(
                token, exchange, order["price"], order["symbol"]
            ),
        )
        # ord_psbl_qty를 우선해 보유 외화만으로 가능한 수량을 사용합니다.
        available = _orderable_quantity(
            response,
            ("ord_psbl_qty", "max_ord_psbl_qty", "ovrs_max_ord_psbl_qty"),
        )
    if available < order["quantity"]:
        raise RuntimeError(
            f"{order['symbol']} 주문 가능 수량 부족: "
            f"필요 {order['quantity']}주, 가능 {available}주"
        )


def wait_for_target_quantity(token: str, order: dict) -> None:
    """보유수량이 목표와 같아질 때까지 기다려 접수와 체결을 구분한다."""
    deadline = time.monotonic() + FILL_TIMEOUT_SECONDS
    account_target = order.get("account_target_quantity", order["target_quantity"])
    while True:
        quantities = current_quantities(token, {order["country"]})
        current = quantities.get(order["symbol"], 0)
        if current == account_target:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"{order['symbol']} 체결 확인 시간 초과: "
                f"계좌 현재 {current}주, 계좌 목표 {account_target}주. "
                "KIS 미체결 내역을 확인하세요."
            )
        time.sleep(FILL_CHECK_SECONDS)


def place_orders(
    token: str, orders: list[dict], on_accepted=None, on_filled=None
) -> None:
    """매도 체결을 확인한 뒤 매수를 진행한다."""
    # 현금을 먼저 확보할 수 있도록 모든 매도를 매수보다 앞에 배치한다.
    ordered = sorted(orders, key=lambda item: item["side"] != "sell")
    for order in ordered:
        ensure_orderable(token, order)
        if order["country"] == "KR":
            result = domestic.order_stock(
                token=token,
                order_type=order["side"],
                stock_code=order["symbol"],
                quantity=order["quantity"],
            )
        else:
            order_exchange = ORDER_EXCHANGE.get(order["exchange"])
            if not order_exchange:
                raise ValueError(f"지원하지 않는 해외 거래소: {order['exchange']}")
            result = overseas.order_stock(
                token=token,
                order_type=order["side"],
                market_code=order_exchange,
                ticker=order["symbol"],
                quantity=order["quantity"],
                price=order["price"],
            )
        if str(result.get("rt_cd", "")) != "0":
            raise RuntimeError(f"{order['symbol']} 주문 실패: {result.get('msg1', '')}")
        # API 성공 코드만으로는 부족하므로 주문번호가 실제로 왔는지도 확인한다.
        output = as_rows(result.get("output"))
        order_no = (
            str(output[0].get("ODNO", output[0].get("odno", ""))).strip()
            if output
            else ""
        )
        if not order_no:
            raise RuntimeError(
                f"{order['symbol']} 주문번호가 없습니다. KIS 주문내역을 확인하세요."
            )
        if on_accepted is not None:
            on_accepted(order, order_no)
        print(f"주문 접수: {order['side']} {order['symbol']} {order['quantity']}주")
        wait_for_target_quantity(token, order)
        if on_filled is not None:
            # 체결 직후 콜백으로 장부를 저장해 후속 주문 실패 시에도 기록을 남긴다.
            on_filled(order, order_no)
        print(f"체결 확인: {order['symbol']} 목표 {order['target_quantity']}주")


def ask_interrupted_recovery(
    country: str, interrupted: dict, scheduler_path: Path, reader=None
) -> bool:
    """중단 주문의 조회·복구와 필요한 잔여 주문 진행을 명시적으로 승인받는다."""
    reader = reader or input
    print(
        f"\n[중단 주문 안전 복구 필요]\n"
        f"{MARKET_NAMES[country]} 시장의 이전 주문 처리가 완료되지 않았습니다: "
        f"{interrupted}\n"
        "KIS 주문·체결내역과 현재 잔고를 확인하여 상태를 복구한 뒤, "
        "필요한 잔여 수량만 다시 주문할까요?\n"
        f"상태 파일: {scheduler_path}\n"
        "불일치·부분체결·미체결 주문이 발견되면 주문하지 않고 상태를 유지합니다."
    )
    try:
        answer = reader("계속하려면 y를 입력하세요 [y/N]: ")
    except (EOFError, KeyboardInterrupt):
        return False
    return str(answer).strip().lower() in {"y", "yes"}


def _execution_records(path: Path) -> list[dict]:
    """실행 로그를 엄격히 읽으며 손상된 한 줄이라도 있으면 복구를 중단한다."""
    if not path.exists():
        raise RuntimeError(f"실행 로그가 없어 중단 주문을 확인할 수 없습니다: {path}")
    records: list[dict] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"실행 로그 {line_number}번째 줄이 손상됐습니다: {path}"
            ) from error
        if not isinstance(record, dict):
            raise RuntimeError(
                f"실행 로그 {line_number}번째 줄 형식이 잘못됐습니다: {path}"
            )
        records.append(record)
    return records


def _record_time(record: dict, path: Path) -> pd.Timestamp:
    """실행 로그의 UTC 시각을 비교 가능한 값으로 검증한다."""
    try:
        timestamp = pd.Timestamp(record["timestamp"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError(f"실행 로그에 유효한 timestamp가 없습니다: {path}") from error
    if timestamp.tzinfo is None:
        raise RuntimeError(f"실행 로그 timestamp에 시간대가 없습니다: {path}")
    return timestamp.tz_convert("UTC")


def _interrupted_orders(
    country: str, interrupted: dict, execution_path: Path
) -> list[dict]:
    """중단 시각 이후 접수됐지만 체결 저장이 끝나지 않은 주문을 찾는다."""
    planned_orders = _validated_interrupted_plan(interrupted)
    try:
        started_at = pd.Timestamp(interrupted["started_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("중단 상태의 started_at 값이 잘못됐습니다.") from error
    if started_at.tzinfo is None:
        raise RuntimeError("중단 상태의 started_at에 시간대가 없습니다.")
    started_at = started_at.tz_convert("UTC")

    accepted: dict[str, dict] = {}
    filled: set[str] = set()
    if planned_orders == [] and not execution_path.exists():
        records = []
    else:
        records = _execution_records(execution_path)
    for record in records:
        if _record_time(record, execution_path) < started_at:
            continue
        event = record.get("event")
        order_no = str(record.get("order_no", "")).strip()
        order = record.get("order")
        if event == "order_accepted":
            if not order_no or not isinstance(order, dict):
                raise RuntimeError("접수 주문 로그의 주문번호 또는 주문 정보가 없습니다.")
            if order.get("country") != country:
                continue
            accepted_record = {
                "order": order,
                "execution_id": str(record.get("execution_id", "")).strip(),
            }
            previous = accepted.get(order_no)
            if previous is not None and previous != accepted_record:
                raise RuntimeError(f"주문번호 {order_no}의 접수 로그가 서로 다릅니다.")
            accepted[order_no] = accepted_record
        elif event in {"order_filled", "order_filled_recovered"} and order_no:
            if isinstance(order, dict) and order.get("country") == country:
                filled.add(order_no)

    if planned_orders is not None:
        unexpected = [
            item["order"]
            for item in accepted.values()
            if item["order"] not in planned_orders
        ]
        if unexpected:
            raise RuntimeError(
                "접수 주문 로그가 중단 상태에 저장된 주문 계획과 다릅니다."
            )
    if not accepted and planned_orders != []:
        raise RuntimeError(
            "중단 시각 이후 접수 주문 로그가 없습니다. 주문 API 응답 전후의 상태를 "
            "판단할 수 없어 자동 복구하지 않습니다."
        )
    return [
        {"order_no": order_no, **item}
        for order_no, item in accepted.items()
        if order_no not in filled
    ]


def _history_date_range(country: str, interrupted: dict) -> tuple[str, str]:
    """중단 시각부터 현재까지를 해당 시장 현지 주문일자로 변환한다."""
    started_at = pd.Timestamp(interrupted["started_at"])
    if started_at.tzinfo is None:
        raise RuntimeError("중단 상태의 started_at에 시간대가 없습니다.")
    timezone = ZoneInfo(MARKET_TIMEZONES[country])
    start = started_at.to_pydatetime().astimezone(timezone).strftime("%Y%m%d")
    end = utc_now().to_pydatetime().astimezone(timezone).strftime("%Y%m%d")
    if end < start:
        raise RuntimeError("중단 주문 조회 종료일이 시작일보다 빠릅니다.")
    return start, end


def inquire_order_history_range(
    token: str, country: str, start_date: str, end_date: str
) -> list[dict]:
    """공유 KIS 모듈을 바꾸지 않고 중단 주문 날짜 범위의 내역을 조회한다."""
    if country == "KR":
        endpoint = kis_config.DOMESTIC_ORDER_HISTORY_ENDPOINT
        tr_id = (
            kis_config.DOMESTIC_ORDER_HISTORY_TR_ID_PAPER
            if kis_config.is_paper()
            else kis_config.DOMESTIC_ORDER_HISTORY_TR_ID_REAL
        )
        params = {
            "CANO": kis_config.ACCOUNT_NO,
            "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
            "INQR_STRT_DT": start_date,
            "INQR_END_DT": end_date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "EXCG_ID_DVSN_CD": "KRX",
        }
        context_size = 100
        output_key = "output1"
    elif country == "US":
        endpoint = kis_config.OVERSEAS_ORDER_HISTORY_ENDPOINT
        paper = kis_config.is_paper()
        tr_id = (
            kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_PAPER
            if paper
            else kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_REAL
        )
        params = {
            "CANO": kis_config.ACCOUNT_NO,
            "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
            # KIS 주문체결 조회는 모의투자에서 전체조회 값을 공란으로만 받는다.
            # 실전투자의 전체조회 값(%)을 모의투자에 보내면 성공 응답이어도
            # 주문 목록이 비어 반환될 수 있다.
            "PDNO": "" if paper else "%",
            "ORD_STRT_DT": start_date,
            "ORD_END_DT": end_date,
            "SLL_BUY_DVSN": "00",
            "CCLD_NCCS_DVSN": "00",
            "OVRS_EXCG_CD": "" if paper else "%",
            "SORT_SQN": "DS",
            "ORD_DT": "",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "CTX_AREA_NK200": "",
            "CTX_AREA_FK200": "",
        }
        context_size = 200
        output_key = "output"
    else:
        raise ValueError(f"지원하지 않는 시장: {country}")

    response = call_with_rate_limit_retry(
        f"{MARKET_NAMES[country]} 중단 주문내역 조회",
        lambda: kis_client.get_all_pages(
            endpoint=endpoint,
            tr_id=tr_id,
            token=token,
            params=params,
            context_size=context_size,
            output_keys=(output_key,),
        ),
    )
    if str(response.get("rt_cd", "")) != "0":
        raise RuntimeError(
            f"{MARKET_NAMES[country]} 주문내역 조회 실패: "
            f"{response.get('msg_cd', '')} / {response.get('msg1', '')}"
        )
    return as_rows(response.get(output_key))


def _strict_quantity(row: dict, fields: tuple[str, ...], label: str) -> int:
    """주문내역 수량 필드를 0 이상 정수로 엄격히 읽는다."""
    for field in fields:
        value = row.get(field)
        if value is None or str(value).strip() == "":
            continue
        text = str(value).replace(",", "").strip()
        try:
            numeric = float(text)
        except ValueError as error:
            raise RuntimeError(f"KIS 주문내역의 {label} 값이 잘못됐습니다: {value}") from error
        if numeric < 0 or not numeric.is_integer():
            raise RuntimeError(f"KIS 주문내역의 {label} 값이 잘못됐습니다: {value}")
        return int(numeric)
    raise RuntimeError(f"KIS 주문내역에서 {label} 필드를 찾지 못했습니다.")


def normalize_order_no(value) -> str:
    """KIS가 생략할 수 있는 주문번호 앞자리 0을 제거해 비교 형식을 맞춘다."""
    text = str(value).strip()
    return text.lstrip("0") or "0"


def _matched_history_row(rows: list[dict], order_no: str, order: dict) -> dict:
    """주문번호와 종목이 정확히 일치하는 KIS 주문내역 한 행을 선택한다."""
    normalized_order_no = normalize_order_no(order_no)
    matches = [
        row
        for row in rows
        if normalize_order_no(row.get("odno", row.get("ODNO", "")))
        == normalized_order_no
    ]
    unique: dict[str, dict] = {
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str): row
        for row in matches
    }
    if len(unique) != 1:
        raise RuntimeError(
            f"주문번호 {order_no}의 KIS 주문내역이 "
            f"{len(unique)}건이라 안전하게 판단할 수 없습니다."
        )
    row = next(iter(unique.values()))
    symbol = str(row.get("pdno", row.get("ovrs_pdno", ""))).strip()
    if not symbol or symbol != str(order.get("symbol", "")).strip():
        raise RuntimeError(
            f"주문번호 {order_no}의 종목이 접수 로그와 다릅니다: "
            f"KIS {symbol or '없음'} / 로그 {order.get('symbol', '')}"
        )
    return row


def recover_interrupted_market(
    token: str,
    country: str,
    interrupted: dict,
    state: dict,
    managed: dict,
    store: RuntimeStore,
) -> None:
    """KIS 근거가 완전히 일치할 때만 중단 상태를 복구한다."""
    unresolved = _interrupted_orders(country, interrupted, store.paths.executions)
    staged_managed = deepcopy(managed)
    recovered_fills: list[dict] = []

    if unresolved:
        start_date, end_date = _history_date_range(country, interrupted)
        history = inquire_order_history_range(token, country, start_date, end_date)
        account_quantities = current_quantities(token, {country})

        for accepted in unresolved:
            order_no = accepted["order_no"]
            order = accepted["order"]
            row = _matched_history_row(history, order_no, order)
            ordered = _strict_quantity(row, ("ft_ord_qty", "ord_qty"), "주문수량")
            filled = _strict_quantity(
                row, ("ft_ccld_qty", "tot_ccld_qty"), "체결수량"
            )
            unfilled = _strict_quantity(row, ("nccs_qty",), "미체결수량")
            expected_ordered = int(order.get("quantity", -1))
            if ordered != expected_ordered or filled + unfilled > ordered:
                raise RuntimeError(
                    f"주문번호 {order_no}의 수량이 접수 로그와 다릅니다: "
                    f"주문 {ordered}, 체결 {filled}, 미체결 {unfilled}, "
                    f"로그 주문 {expected_ordered}"
                )

            symbol = order["symbol"]
            actual = account_quantities.get(symbol, 0)
            account_before = int(order.get("account_current_quantity", -1))
            account_target = int(order.get("account_target_quantity", -1))
            strategy_before = int(order.get("current_quantity", -1))
            strategy_target = int(order.get("target_quantity", -1))
            side = order.get("side")
            if side not in {"buy", "sell"}:
                raise RuntimeError(
                    f"주문번호 {order_no}의 매수·매도 구분이 잘못됐습니다: {side}"
                )
            direction = 1 if side == "buy" else -1
            if min(
                account_before,
                account_target,
                strategy_before,
                strategy_target,
            ) < 0 or (
                account_target - account_before != direction * ordered
                or strategy_target - strategy_before != direction * ordered
            ):
                raise RuntimeError(
                    f"주문번호 {order_no}의 주문 전후 목표수량 계산이 맞지 않습니다."
                )
            strategy_actual = int(
                staged_managed.get("positions", {}).get(symbol, {}).get("quantity", 0)
            )

            if filled == ordered and unfilled == 0:
                if actual != account_target:
                    raise RuntimeError(
                        f"{symbol} 실제 잔고가 체결 목표와 다릅니다: "
                        f"실제 {actual}주 / 목표 {account_target}주"
                    )
                if strategy_actual == strategy_target:
                    recovered_fills.append(accepted)
                    continue
                if strategy_actual != strategy_before:
                    raise RuntimeError(
                        f"{symbol} 전략 장부가 주문 전·후 어느 수량과도 일치하지 "
                        f"않습니다: 장부 {strategy_actual}주"
                    )
                apply_filled_order(staged_managed, order)
                recovered_fills.append(accepted)
            elif filled == 0 and unfilled == 0:
                if actual != account_before or strategy_actual != strategy_before:
                    raise RuntimeError(
                        f"{symbol} 미체결 종료 주문의 잔고가 주문 전 수량과 다릅니다: "
                        f"계좌 {actual}/{account_before}주, "
                        f"장부 {strategy_actual}/{strategy_before}주"
                    )
            else:
                raise RuntimeError(
                    f"주문번호 {order_no}가 아직 부분체결 또는 미체결 상태입니다: "
                    f"체결 {filled}주, 미체결 {unfilled}주. "
                    "중복 주문 방지를 위해 상태를 유지합니다."
                )

    if staged_managed != managed:
        store.save_ledger(staged_managed)
        managed.clear()
        managed.update(staged_managed)
    for accepted in recovered_fills:
        execution_details = {
            "order_no": accepted["order_no"],
            "order": accepted["order"],
        }
        if accepted.get("execution_id"):
            execution_details["execution_id"] = accepted["execution_id"]
        store.append_execution(
            "order_filled_recovered",
            execution_details,
        )

    staged_state = deepcopy(state)
    staged_state["in_progress"].pop(country, None)
    store.save_scheduler(staged_state)
    state.clear()
    state.update(staged_state)
    store.append_execution(
        "interrupted_cycle_recovered",
        {
            "country": country,
            "cycle": interrupted.get("cycle"),
            "recovered_fills": [item["order_no"] for item in recovered_fills],
        },
    )
    print(
        f"{MARKET_NAMES[country]} 중단 주문 복구가 완료됐습니다. "
        "최신 잔고로 주문 계획을 다시 계산합니다."
    )


# =============================================================================
# 10. 거래소 캘린더와 시간 계산
# =============================================================================

def utc_now() -> pd.Timestamp:
    """한국·미국 시간 비교의 기준이 되는 현재 UTC 시각을 반환한다."""
    return pd.Timestamp.now(tz="UTC")


def next_market_open(country: str, now: pd.Timestamp | None = None) -> pd.Timestamp:
    """현재 정규장이면 현재 시각, 아니면 다음 정규장 개장 시각을 반환한다."""
    calendar = xcals.get_calendar(MARKET_CALENDARS[country])
    minute = (now if now is not None else utc_now()).floor("min")
    if calendar.is_open_on_minute(minute):
        return minute
    return calendar.next_open(minute)


def market_is_open(country: str, now: pd.Timestamp | None = None) -> bool:
    """휴장일을 포함한 공식 거래소 캘린더로 현재 정규장 여부를 확인한다."""
    calendar = xcals.get_calendar(MARKET_CALENDARS[country])
    minute = (now if now is not None else utc_now()).floor("min")
    return bool(calendar.is_open_on_minute(minute))


def format_market_time(country: str, moment: pd.Timestamp) -> str:
    """UTC 시각을 해당 거래소의 현지 시각 문자열로 바꾼다."""
    local = moment.to_pydatetime().astimezone(ZoneInfo(MARKET_TIMEZONES[country]))
    return local.strftime("%Y-%m-%d %H:%M %Z")


def wait_until(moment: pd.Timestamp) -> None:
    """지정 시각까지 짧게 나누어 대기해 장기 스케줄러를 유지한다."""
    while True:
        remaining = (moment - utc_now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(SCHEDULER_POLL_SECONDS, remaining))


# =============================================================================
# 11. 스케줄러 잠금과 분리된 런타임 상태 연결
# =============================================================================

def make_runtime_store(capital_krw: int) -> RuntimeStore:
    """현재 KIS 환경·계좌·전략에 해당하는 분리 저장소를 선택한다."""
    return RuntimeStore(
        runtime_root=RUNTIME_ROOT,
        environment=kis_config.KIS_ENV,
        account_no=kis_config.ACCOUNT_NO or "",
        product_code=kis_config.ACCOUNT_PRODUCT_CODE,
        initial_capital_krw=capital_krw,
    )


def _pid_is_running(pid: int) -> bool:
    """잠금 파일의 PID가 현재 운영체제에서 살아 있는지 확인한다."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True

    if os.name == "nt":
        # Windows에는 신호 0을 이용한 PID 확인이 없으므로 프로세스 핸들을 조회한다.
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        still_active = 259
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        )
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if not handle:
            # 접근 거부는 프로세스가 존재하지만 조회 권한만 없는 경우다.
            return ctypes.get_last_error() == 5
        try:
            exit_code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _reclaim_stale_lock(path: Path) -> bool:
    """종료된 PID의 잠금만 제거하며, 경합 중 바뀐 파일은 건드리지 않는다."""
    try:
        original = path.stat()
        owner_pid = int(path.read_text(encoding="ascii").strip())
    except (FileNotFoundError, OSError, ValueError):
        return False

    if _pid_is_running(owner_pid):
        return False

    try:
        current = path.stat()
    except FileNotFoundError:
        return True
    # 다른 프로세스가 그 사이 새 잠금을 만들었다면 삭제하지 않는다.
    if (current.st_ino, current.st_ctime_ns, current.st_mtime_ns, current.st_size) != (
        original.st_ino,
        original.st_ctime_ns,
        original.st_mtime_ns,
        original.st_size,
    ):
        return True
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


@contextmanager
def scheduler_lock(path: Path):
    """Windows와 Linux에서 동일하게 중복 스케줄러 실행을 막는다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    for attempt in range(2):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError as error:
            if attempt == 0 and _reclaim_stale_lock(path):
                continue
            try:
                owner = path.read_text(encoding="ascii").strip()
            except OSError:
                owner = "확인 불가"
            raise RuntimeError(
                f"다른 포트폴리오 스케줄러가 실행 중입니다(PID {owner}): {path}"
            ) from error
    if descriptor is None:  # 방어적 검사: 정상 흐름에서는 도달하지 않는다.
        raise RuntimeError(f"스케줄러 잠금을 만들지 못했습니다: {path}")
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as lock_file:
            lock_file.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)

def market_cycle(country: str, moment: pd.Timestamp) -> str:
    """국가별 현지 시각을 월간 실행 키(YYYY-MM)로 바꾼다."""
    local = moment.to_pydatetime().astimezone(ZoneInfo(MARKET_TIMEZONES[country]))
    return local.strftime("%Y-%m")


def quarter_key(moment: pd.Timestamp) -> str:
    """분기별 분석 갱신 여부를 판단할 한국 기준 분기 키를 만든다."""
    local = moment.to_pydatetime().astimezone(ZoneInfo("Asia/Seoul"))
    return f"{local.year}-Q{((local.month - 1) // 3) + 1}"


def next_monthly_check(
    country: str, last_completed_cycle: str | None, now: pd.Timestamp | None = None
) -> pd.Timestamp:
    """이번 달 미실행이면 다음 개장, 완료했으면 다음 달 첫 개장을 반환한다."""
    now = now if now is not None else utc_now()
    current_cycle = market_cycle(country, now)
    if last_completed_cycle != current_cycle:
        return next_market_open(country, now)

    local = now.to_pydatetime().astimezone(ZoneInfo(MARKET_TIMEZONES[country]))
    if local.month == 12:
        next_month = date(local.year + 1, 1, 1)
    else:
        next_month = date(local.year, local.month + 1, 1)
    calendar = xcals.get_calendar(MARKET_CALENDARS[country])
    session = calendar.date_to_session(pd.Timestamp(next_month), direction="next")
    return calendar.session_open(session)


def refresh_analysis_for_quarter(
    state: dict, moment: pd.Timestamp, store: RuntimeStore
) -> None:
    """분기 첫 실행 때 가격·환율 데이터를 수집하고 분석 결과를 갱신한다."""
    quarter = quarter_key(moment)
    if state.get("analysis_quarter") == quarter:
        return

    print(f"\n{quarter} 분기 데이터 갱신과 목표 비중 재계산을 시작합니다.")
    from strategy.dataforportfolio import FX_SYMBOL, analyze, collect_all

    collect_all(FX_SYMBOL)
    analyze()
    state["analysis_quarter"] = quarter
    store.save_scheduler(state)


def validate_target_age(target: dict) -> None:
    """시장 개장을 기다리는 동안 분석 결과가 너무 오래되지 않았는지 확인한다."""
    as_of = datetime.strptime(target["as_of"], "%Y-%m-%d").date()
    age = (date.today() - as_of).days
    if age < 0 or age > MAX_SIGNAL_AGE_DAYS:
        raise RuntimeError(
            f"대기 중 분석 결과가 유효기간을 벗어났습니다: {as_of} ({age}일)"
        )


# =============================================================================
# 12. 월간 리밸런싱 장기 실행 루프
# =============================================================================

def execute_by_market_schedule(
    capital_krw: int,
    threshold: float,
    liquidate_unselected: bool,
    once: bool = False,
) -> None:
    """하나의 프로세스만 월간 스케줄을 실행하게 한다."""
    store = make_runtime_store(capital_krw)
    with scheduler_lock(store.paths.lock):
        _execute_by_market_schedule(
            capital_krw, threshold, liquidate_unselected, once, store
        )


def _execute_by_market_schedule(
    capital_krw: int,
    threshold: float,
    liquidate_unselected: bool,
    once: bool,
    store: RuntimeStore,
) -> None:
    """매월 비중을 점검하고 분기마다 분석을 갱신하는 장기 실행 본체다."""
    _, state, managed = store.load_or_initialize(LEGACY_SCHEDULER_STATE_FILE)
    # 장부가 없는 구버전 상태를 실제 계좌 잔고로 임의 복원하지 않는다.
    require_reconciled(managed)
    # 주문 대기나 중단 주문 복구에 들어가기 전에 전략 보유현황부터 보여준다.
    startup_target = load_selected_portfolio()
    startup_token = issue_access_token()
    print_managed_portfolio_status(
        startup_token, startup_target, managed, store.paths.executions
    )
    store.append_execution(
        "scheduler_started",
        {
            "capital_krw": capital_krw,
            "threshold": threshold,
            "liquidate_unselected": liquidate_unselected,
            "once": once,
        },
    )
    started_at = utc_now()
    target_cycles = {
        country: market_cycle(country, started_at) for country in MARKET_CALENDARS
    }
    completed_this_run = {
        country
        for country, cycle in target_cycles.items()
        if once and state["completed_cycles"].get(country) == cycle
    }

    # --once가 아니면 다음 달의 거래소 개장까지 계속 반복한다.
    while True:
        openings = {
            country: next_monthly_check(
                country, state["completed_cycles"].get(country)
            )
            for country in MARKET_CALENDARS
            if country not in completed_this_run
        }
        if once:
            # --once는 시작할 때의 월을 벗어난 다음 달 주문까지 기다리지 않습니다.
            for country, opening in list(openings.items()):
                if market_cycle(country, opening) != target_cycles[country]:
                    completed_this_run.add(country)
                    openings.pop(country)
        if not openings:
            if once:
                return
            completed_this_run.clear()
            continue
        # 한국과 미국 중 더 먼저 열리는 시장부터 하나씩 처리한다.
        country = min(openings, key=openings.get)
        opening = openings[country]
        if opening > utc_now():
            print(
                f"{MARKET_NAMES[country]} 시장 다음 정규장까지 대기: "
                f"{format_market_time(country, opening)}"
            )
            wait_until(opening)

        now = utc_now()
        if not market_is_open(country, now):
            continue

        cycle = market_cycle(country, now)
        if once and cycle != target_cycles[country]:
            completed_this_run.add(country)
            continue
        # 주문 도중 비정상 종료된 흔적은 사용자 승인과 KIS 근거가 있어야 복구한다.
        recovered_this_cycle = False
        interrupted = state["in_progress"].get(country)
        if interrupted:
            if not ask_interrupted_recovery(
                country, interrupted, store.paths.scheduler
            ):
                print("복구를 취소했습니다. 기존 상태를 변경하지 않고 종료합니다.")
                return
            token = issue_access_token()
            recover_interrupted_market(
                token, country, interrupted, state, managed, store
            )
            recovered_this_cycle = True

        refresh_analysis_for_quarter(state, now, store)
        now = utc_now()
        if not market_is_open(country, now):
            print(
                f"{MARKET_NAMES[country]} 데이터 갱신 중 정규장이 종료되어 "
                "다음 개장까지 다시 대기합니다."
            )
            continue
        target = load_selected_portfolio()
        validate_target_age(target)
        print_selected_portfolio(target)
        print(f"\n{MARKET_NAMES[country]} 시장 정규장 확인, 주문 계획을 갱신합니다.")
        token = issue_access_token()
        # 최초 고정 예산이 아니라 전략 장부의 최신 평가금액으로 목표 수량을 계산한다.
        if recovered_this_cycle:
            managed_value, estimated_cash, holdings_value = (
                print_managed_portfolio_status(
                    token,
                    target,
                    managed,
                    store.paths.executions,
                    title="복구 후 포트폴리오 전략 보유현황",
                )
            )
        else:
            managed_value, estimated_cash, holdings_value = managed_portfolio_value(
                token, target, managed
            )
        if managed_value <= 0:
            raise RuntimeError("전략 포트폴리오 평가금액이 0원 이하입니다.")
        if not recovered_this_cycle:
            print(
                f"전략 평가금액: {managed_value:,.0f}원 "
                f"(추정 현금 {estimated_cash:,.0f}원, "
                f"보유종목 {holdings_value:,.0f}원)"
            )
        orders = build_order_plan(
            token,
            target,
            managed_value,
            threshold,
            liquidate_unselected=liquidate_unselected,
            countries={country},
            managed_portfolio=managed,
        )
        print_plan(orders, execute=True, country=country)
        print(f"KIS 환경: {kis_config.KIS_ENV}")
        # 주문 전에 진행 상태를 저장해 프로세스가 중단되어도 흔적이 남게 한다.
        interrupted_marker = {
            "cycle": cycle,
            "started_at": utc_now().isoformat(),
            "planned_orders": deepcopy(orders),
            "plan_fingerprint": order_plan_fingerprint(orders),
        }
        state["in_progress"][country] = interrupted_marker
        store.save_scheduler(state)

        accepted_execution_ids: dict[str, str] = {}

        def record_accepted_order(order: dict, order_no: str) -> None:
            execution_id = order_execution_id(
                interrupted_marker["started_at"], country, order_no, order
            )
            accepted_execution_ids[order_no] = execution_id
            store.append_execution(
                "order_accepted",
                {
                    "order_no": order_no,
                    "order": order,
                    "execution_id": execution_id,
                },
            )

        def record_filled_order(order: dict, order_no: str) -> None:
            """종목 하나가 체결될 때마다 전략 장부를 즉시 디스크에 저장한다."""
            apply_filled_order(managed, order)
            store.save_ledger(managed)
            store.append_execution(
                "order_filled",
                {
                    "order_no": order_no,
                    "order": order,
                    "execution_id": accepted_execution_ids[order_no],
                },
            )

        place_orders(
            token,
            orders,
            on_accepted=record_accepted_order,
            on_filled=record_filled_order,
        )
        state["in_progress"].pop(country, None)
        state["completed_cycles"][country] = cycle
        store.save_scheduler(state)
        store.append_execution(
            "market_cycle_completed", {"country": country, "cycle": cycle}
        )
        completed_this_run.add(country)

        if once and completed_this_run == set(MARKET_CALENDARS):
            return


# =============================================================================
# 13. 명령행 인터페이스와 실행 진입점
# =============================================================================

def print_startup_guide() -> None:
    """옵션 없이 실행했을 때 주문 없이 간단 사용설명서만 보여준다."""
    print(
        f"""
[KIS 포트폴리오 자동매매 사용설명서]

현재 KIS 환경: {kis_config.KIS_ENV}

1. 가격·환율 데이터 수집, 조합 분석 및 최종 비중 확정
   python strategy\\dataforportfolio.py run

2. 주문 없이 포트폴리오와 주문 계획 확인 (DRY RUN)
   python strategy/portfolio.py --capital-krw 10000000

3. 이번 달 한국·미국 주문을 처리한 뒤 종료
   python strategy/portfolio.py --capital-krw 10000000 --execute --once

4. 종료하지 않고 매월 리밸런싱 계속 실행
   python strategy/portfolio.py --capital-krw 10000000 --execute

선택 옵션
   --threshold 0.03          리밸런싱 최소 차이(기본 3%)
   --liquidate-unselected   전략에서 탈락한 추적 종목도 매도

주의
   --execute가 없으면 주문하지 않습니다.
   KIS_ENV=paper는 모의투자, KIS_ENV=real은 실전투자입니다.
   장기 실행 전에는 반드시 DRY RUN과 모의투자로 먼저 확인하세요.
""".strip()
    )


def main() -> None:
    """명령행 옵션을 해석해 드라이런 또는 장기 주문 스케줄러를 시작한다."""
    if len(sys.argv) == 1:
        print_startup_guide()
        return

    parser = argparse.ArgumentParser(description="분석 결과 기반 KIS 포트폴리오 주문")
    parser.add_argument("--capital-krw", type=int, required=True, help="목표 투자금액(원)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=DEFAULT_REBALANCE_THRESHOLD,
        help="최소 리밸런싱 차이, 기본 0.03(3%%)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="매월 각 시장의 정규장에서 실제 주문 실행. 생략하면 DRY_RUN",
    )
    parser.add_argument(
        "--liquidate-unselected",
        action="store_true",
        help="후보군 중 목표 4종목에서 탈락한 보유종목도 전량 매도 계획에 포함",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="이번 월간 점검만 마친 뒤 종료. 생략하면 다음 달까지 계속 대기",
    )
    args = parser.parse_args()
    if args.capital_krw <= 0:
        parser.error("--capital-krw는 0보다 커야 합니다.")
    if not 0 <= args.threshold < 1:
        parser.error("--threshold는 0 이상 1 미만이어야 합니다.")

    if args.execute:
        # --execute가 있을 때만 실제 KIS 주문 함수가 호출된다.
        execute_by_market_schedule(
            args.capital_krw,
            args.threshold,
            args.liquidate_unselected,
            once=args.once,
        )
    else:
        # 드라이런도 실제 가격·잔고는 조회하지만 주문 API는 호출하지 않는다.
        target = load_selected_portfolio()
        store = make_runtime_store(args.capital_krw)
        _, _, managed = store.load_or_initialize(LEGACY_SCHEDULER_STATE_FILE)
        if managed.get("requires_reconciliation"):
            print(
                "\n[DRY RUN 상태 점검]\n"
                "구버전 스케줄 기록은 보존·이관했지만 전략 전용 장부는 "
                "자동 복원하지 않았습니다.\n"
                "기존 주문·체결과 전략 귀속 잔고를 확인하기 전에는 실제 주문이 "
                "차단됩니다.\n"
                f"스케줄 상태: {store.paths.scheduler}\n"
                f"전략 장부  : {store.paths.ledger}\n"
                f"구버전 백업: {store.paths.legacy_backup}"
            )
            return
        token = issue_access_token()
        managed_value, estimated_cash, holdings_value = print_managed_portfolio_status(
            token, target, managed, store.paths.executions
        )
        print_selected_portfolio(target)
        orders = build_order_plan(
            token,
            target,
            managed_value,
            args.threshold,
            liquidate_unselected=args.liquidate_unselected,
            managed_portfolio=managed,
        )
        print_plan(orders, execute=False)


if __name__ == "__main__":
    # 다른 파일에서 import할 때는 실행하지 않고 직접 실행할 때만 시작한다.
    main()
