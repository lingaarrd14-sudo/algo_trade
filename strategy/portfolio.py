"""
파일명: portfolio.py
역할: 최소분산 포트폴리오(한국+미국)로 목표 비중을 계산해 저장하고, 5/25 허용폭을
      벗어나면 시장별로 리밸런싱 주문을 실행하는 자동매매 파일.
      목표 비중은 7일마다 자동으로 다시 계산한다.

실행 예시 (프로젝트 루트에서):
  python strategy/portfolio.py                          # 명령어 목록 출력
  python strategy/portfolio.py analyze                  # 목표 비중 계산 후 저장
  python strategy/portfolio.py trade                    # 계속 실행, 드라이런 (주문 안 함)
  python strategy/portfolio.py trade --execute          # 계속 실행, 실제 주문
  python strategy/portfolio.py trade --once kr          # 지금 바로 한국장 1회 (드라이런)
  python strategy/portfolio.py trade --once us --execute
"""

import argparse
import json
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yfinance as yf
from pypfopt import EfficientFrontier, risk_models

sys.path.append(str(Path(__file__).resolve().parent.parent))

from kis import kis_config
from kis.kis_auth import issue_access_token
import kis.kis_domestic as domestic
import kis.kis_overseas as overseas


# =========================================================
# 1. 설정값
# =========================================================
# 후보 종목 (최소분산 계산으로 이 중 최대 10개를 고름)
KR_CANDIDATES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "005380": "현대차", "000270": "기아",
    "068270": "셀트리온", "035420": "NAVER", "105560": "KB금융",
    "055550": "신한지주", "005490": "POSCO홀딩스", "035720": "카카오",
    "012330": "현대모비스", "051910": "LG화학", "028260": "삼성물산",
}
# 미국 종목: 티커 -> (시세 조회용 거래소 코드, 주문용 거래소 코드)
US_CANDIDATES = {
    "AAPL": ("NAS", "NASD"), "MSFT": ("NAS", "NASD"), "NVDA": ("NAS", "NASD"),
    "AMZN": ("NAS", "NASD"), "GOOGL": ("NAS", "NASD"), "META": ("NAS", "NASD"),
    "AVGO": ("NAS", "NASD"), "COST": ("NAS", "NASD"),
    "JPM": ("NYS", "NYSE"), "V": ("NYS", "NYSE"), "JNJ": ("NYS", "NYSE"),
    "WMT": ("NYS", "NYSE"), "PG": ("NYS", "NYSE"), "XOM": ("NYS", "NYSE"),
    "KO": ("NYS", "NYSE"),
}

MAX_STOCKS = 10            # 최대 보유 종목 수
LOOKBACK = "1y"            # 공분산 계산 기간
BAND_ABS = 0.05            # 5/25 규칙: 절대 허용폭 5%p
BAND_REL = 0.25            # 5/25 규칙: 상대 허용폭 25%
MIN_TRADE_RATIO = 0.005    # 총자산의 0.5% 미만 주문은 생략
API_DELAY = 1.0            # KIS API 호출 간격(초)
MAX_TRIES = 3              # 실행 실패 시 같은 날 재시도 횟수 (서버 응답 지연 대비)
QUERY_TRIES = 3            # 조회 API 1건당 시도 횟수 (타임아웃·연결 오류 시)
QUERY_RETRY_DELAY = 5      # 조회 재시도 간격(초)
REANALYZE_DAYS = 7         # 목표 비중 재계산 주기(일)
WEIGHTS_FILE = Path(__file__).resolve().parent / "target_weights.json"  # 목표 비중 저장 파일

# 시장별 실행 시간대 (현지 시각 기준, 이 구간 안에서 하루 1번 실행)
MARKETS = {
    "kr": {"tz": ZoneInfo("Asia/Seoul"), "start": "09:10", "end": "15:20"},
    "us": {"tz": ZoneInfo("America/New_York"), "start": "09:40", "end": "15:50"},
}


# =========================================================
# 2. 공통 유틸
# =========================================================
def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")


def pad(text: str, width: int, right: bool = False) -> str:
    """터미널 표시 폭 기준 정렬 (한글은 2칸으로 계산)."""
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    gap = " " * max(width - w, 0)
    return gap + text if right else text + gap


def to_float(val) -> float:
    try:
        return float(str(val).replace(",", "").strip() or 0)
    except (ValueError, TypeError):
        return 0.0


def market_of(key: str) -> str:
    return "kr" if key in KR_CANDIDATES else "us"


def name_of(key: str) -> str:
    return KR_CANDIDATES.get(key, key)


def check_ok(res: dict, title: str) -> dict:
    """KIS 응답이 실패면 예외를 던진다."""
    if str(res.get("rt_cd")) != "0":
        raise RuntimeError(f"{title} 실패: {res.get('msg_cd')} {res.get('msg1')}")
    return res


def as_list(rows) -> list:
    return [rows] if isinstance(rows, dict) else (rows or [])


class OrderUncertainError(RuntimeError):
    """주문 전송 후 응답을 못 받아 체결 여부를 알 수 없음. 재시도하면 중복 주문 위험."""


def call_query(func, *args):
    """조회 API 호출. 타임아웃·연결 오류면 잠시 쉬고 다시 시도한다 (주문에는 쓰지 않는다)."""
    for i in range(1, QUERY_TRIES + 1):
        try:
            return func(*args)
        except requests.exceptions.RequestException as exc:
            if i == QUERY_TRIES:
                raise
            log(f"  조회 응답 지연({type(exc).__name__}) {i}/{QUERY_TRIES} -> {QUERY_RETRY_DELAY}초 후 재시도")
            time.sleep(QUERY_RETRY_DELAY)


# =========================================================
# 3. 목표 비중 계산 (yfinance + 최소분산)
# =========================================================
def load_prices():
    """후보 종목의 원화 기준 종가와 최신 원/달러 환율을 반환한다."""
    kr = {f"{code}.KS": code for code in KR_CANDIDATES}
    tickers = list(kr) + list(US_CANDIDATES) + ["KRW=X"]
    df = yf.download(tickers, period=LOOKBACK, auto_adjust=True, progress=False)["Close"]

    fx = df["KRW=X"].ffill()
    prices = df[list(kr)].rename(columns=kr).join(df[list(US_CANDIDATES)].mul(fx, axis=0))

    # 데이터가 거의 없는 종목은 제외, 두 시장 모두 열린 날만 사용
    prices = prices.dropna(axis=1, thresh=int(len(prices) * 0.8)).dropna()
    return prices, float(fx.iloc[-1])


def min_variance(prices) -> dict:
    """공매도 없는 최소분산 비중 (Ledoit-Wolf 축소 공분산)."""
    cov = risk_models.CovarianceShrinkage(prices).ledoit_wolf()
    ef = EfficientFrontier(None, cov, weight_bounds=(0, 1))
    ef.min_volatility()
    return {k: w for k, w in ef.clean_weights().items() if w > 0}


def calc_target_weights(prices) -> dict:
    """후보 전체로 최소분산 -> 비중 상위 MAX_STOCKS개 -> 다시 최소분산."""
    first = min_variance(prices)
    top = sorted(first, key=first.get, reverse=True)[:MAX_STOCKS]
    return min_variance(prices[top])


def get_fx() -> float:
    """최신 원/달러 환율."""
    return float(yf.Ticker("KRW=X").history(period="5d")["Close"].iloc[-1])


def analyze() -> dict:
    """목표 비중을 새로 계산해 파일에 저장한다."""
    prices, _ = load_prices()
    target = calc_target_weights(prices)
    data = {"date": date.today().isoformat(), "weights": target}
    WEIGHTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"목표 비중 계산 완료 -> {WEIGHTS_FILE.name}")
    for key in sorted(target, key=target.get, reverse=True):
        log(pad(name_of(key), 18) + f"{target[key]:>8.1%}")
    return target


def load_target() -> dict:
    """저장된 목표 비중을 읽는다. 없거나 REANALYZE_DAYS일 이상 지났으면 새로 계산한다."""
    if WEIGHTS_FILE.exists():
        saved = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        age = (date.today() - date.fromisoformat(saved["date"])).days
        if age < REANALYZE_DAYS:
            log(f"저장된 목표 비중 사용 ({saved['date']} 계산, {age}일 경과)")
            return saved["weights"]
    log("목표 비중이 없거나 오래되어 새로 계산합니다.")
    return analyze()


# =========================================================
# 4. 계좌 현황 (KIS 잔고 조회)
# =========================================================
def get_account(token: str, fx: float) -> dict:
    """보유 수량·평가금액(원화)·통화별 현금을 조회한다. 후보 외 종목은 무시한다."""
    qty, value = {}, {}

    dom = check_ok(call_query(domestic.inquire_balance, token), "국내 잔고 조회")
    for item in as_list(dom.get("output1")):
        code = str(item.get("pdno", "")).strip()
        q = int(to_float(item.get("hldg_qty")))
        if code in KR_CANDIDATES and q > 0:
            qty[code] = q
            value[code] = q * to_float(item.get("prpr"))
    summary = as_list(dom.get("output2"))
    cash_krw = to_float(summary[0].get("dnca_tot_amt")) if summary else 0.0
    time.sleep(API_DELAY)

    # NASD 조회 한 번으로 나스닥·뉴욕 보유 종목이 모두 나온다 (모의투자에서 확인)
    ovs = check_ok(call_query(overseas.inquire_balance, token), "해외 잔고 조회")
    for item in as_list(ovs.get("output1")):
        ticker = str(item.get("ovrs_pdno", "")).strip()
        q = int(to_float(item.get("ovrs_cblc_qty")))
        if ticker in US_CANDIDATES and q > 0:
            qty[ticker] = q
            value[ticker] = q * to_float(item.get("now_pric2")) * fx
    time.sleep(API_DELAY)

    amt = check_ok(call_query(overseas.inquire_position_amount, token), "해외 주문가능금액 조회")
    # ovrs_ord_psbl_amt: 외화 기준 주문가능금액 (frcr_ord_psbl_amt1은 원화 포함 '통합' 금액이라 중복 계산됨)
    cash_usd = to_float(amt.get("output", {}).get("ovrs_ord_psbl_amt"))
    time.sleep(API_DELAY)

    total = cash_krw + cash_usd * fx + sum(value.values())
    return {"qty": qty, "value": value, "cash_krw": cash_krw, "cash_usd": cash_usd, "total": total}


# =========================================================
# 5. 리밸런싱 판단 (5/25 규칙)
# =========================================================
def find_breaches(target: dict, current: dict) -> list:
    """허용폭을 벗어났고, 고칠 만큼 차이가 큰(최소 주문 금액 이상) 종목 목록."""
    breaches = []
    for key in set(target) | set(current):
        t, c = target.get(key, 0.0), current.get(key, 0.0)
        band = min(BAND_ABS, BAND_REL * t)  # 목표 0%면 허용폭 0 -> 보유 중이면 매도 대상
        if abs(c - t) > band and abs(c - t) >= MIN_TRADE_RATIO:
            breaches.append(key)
    return breaches


# =========================================================
# 6. 주문 실행 (시장별)
# =========================================================
def get_price(token: str, key: str) -> float:
    """주문 수량 계산용 현재가 (국내: 원, 해외: 달러)."""
    if market_of(key) == "kr":
        res = check_ok(call_query(domestic.inquire_price, token, key), f"{key} 현재가 조회")
        price = to_float(res.get("output", {}).get("stck_prpr"))
    else:
        res = check_ok(call_query(overseas.inquire_price, token, US_CANDIDATES[key][0], key), f"{key} 현재가 조회")
        price = to_float(res.get("output", {}).get("last"))
    time.sleep(API_DELAY)
    if price <= 0:
        raise RuntimeError(f"{key} 현재가가 0입니다 (장 운영 여부 확인)")
    return price


def send_order(token: str, key: str, side: str, q: int, price: float) -> None:
    """주문 1건 전송. 응답을 못 받으면 재시도하지 않고 OrderUncertainError로 멈춘다."""
    try:
        if market_of(key) == "kr":
            res = domestic.order_stock(token=token, order_type=side, stock_code=key, quantity=q)  # 시장가
        else:
            # 미국은 지정가만 가능 -> 조회한 현재가로 주문
            res = overseas.order_stock(token=token, order_type=side, market_code=US_CANDIDATES[key][1],
                                       ticker=key, quantity=q, price=round(price, 2))
    except requests.exceptions.RequestException as exc:
        raise OrderUncertainError(f"{name_of(key)} {side} {q}주 주문 응답 없음({type(exc).__name__}). "
                                  "체결 여부를 cli [5]번 메뉴로 직접 확인하세요.") from exc
    status = "성공" if str(res.get("rt_cd")) == "0" else "실패"
    log(f"  주문 {status}: {name_of(key)} {side} {q}주 / {res.get('msg1', '')}")
    time.sleep(API_DELAY)


def rebalance_market(token: str, market: str, target: dict, account: dict, fx: float, execute: bool) -> None:
    """해당 시장 종목만 목표 금액에 맞게 매도 먼저, 매수 나중에 주문한다."""
    rate = 1.0 if market == "kr" else fx  # 현지 통화 -> 원화
    total = account["total"]
    keys = [k for k in set(target) | set(account["qty"]) if market_of(k) == market]

    orders = []
    for key in keys:
        diff_krw = target.get(key, 0.0) * total - account["value"].get(key, 0.0)
        if abs(diff_krw) < MIN_TRADE_RATIO * total:
            continue
        price = get_price(token, key)
        held = account["qty"].get(key, 0)
        if key not in target:
            q = held  # 목표 0% 종목은 전량 매도
        else:
            q = int(abs(diff_krw) / rate / price)
            if diff_krw < 0:
                q = min(q, held)  # 보유 수량 이상 매도 불가
        if q > 0:
            orders.append((key, "sell" if diff_krw < 0 else "buy", q, price))

    if not orders:
        log("  이 시장에서 낼 주문이 없습니다.")
        return

    sells = [o for o in orders if o[1] == "sell"]
    buys = [o for o in orders if o[1] == "buy"]

    # 현금이 부족하면 모든 매수를 같은 비율로 축소 (매도 대금 포함)
    cash = (account["cash_krw"] if market == "kr" else account["cash_usd"]) + sum(q * p for _, _, q, p in sells)
    need = sum(q * p for _, _, q, p in buys)
    if need > cash:
        ratio = cash / need
        log(f"  현금 부족: 매수 수량을 {ratio:.0%}로 축소")
        buys = [(k, s, int(q * ratio), p) for k, s, q, p in buys]

    # 매도 먼저 (매도 대금으로 매수 가능하도록)
    for key, side, q, price in sells + buys:
        if q <= 0:
            continue
        if execute:
            send_order(token, key, side, q, price)
        else:
            log(f"  [드라이런] {name_of(key)} {side} {q}주 (현재가 {price:,.2f})")


# =========================================================
# 7. 1회 실행
# =========================================================
def run_once(market: str, execute: bool) -> None:
    log(f"===== {market.upper()} 실행 시작 ({'실제 주문' if execute else '드라이런'}) =====")

    target = load_target()
    fx = get_fx()

    token = call_query(issue_access_token)
    account = get_account(token, fx)
    total = account["total"]
    if total <= 0:
        raise RuntimeError("총자산이 0입니다")
    current = {k: v / total for k, v in account["value"].items()}

    log(f"총자산 {total:,.0f}원 (원화 현금 {account['cash_krw']:,.0f}원, "
        f"달러 현금 ${account['cash_usd']:,.2f}, 환율 {fx:,.2f})")
    log(pad("종목", 18) + pad("목표", 8, True) + pad("현재", 8, True))
    for key in sorted(set(target) | set(current), key=lambda k: -target.get(k, 0)):
        log(pad(name_of(key), 18) + f"{target.get(key, 0):>8.1%}{current.get(key, 0):>8.1%}")

    breaches = find_breaches(target, current)
    if not breaches:
        log("모든 종목이 허용폭 안에 있어 리밸런싱하지 않습니다.")
        return

    log(f"허용폭 이탈: {', '.join(name_of(k) for k in breaches)} -> {market.upper()} 종목 리밸런싱")
    rebalance_market(token, market, target, account, fx, execute)


# =========================================================
# 8. 명령 처리 및 계속 실행 루프
# =========================================================
def main() -> None:
    # 명령 없이 실행하거나 -h 입력 시 상단 docstring(실행 예시 포함)을 출력
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", title="명령어")
    sub.add_parser("analyze", help="목표 비중 계산 후 저장")
    trade = sub.add_parser("trade", help="목표 비중에 맞춰 리밸런싱 (비중은 7일마다 자동 재계산)")
    trade.add_argument("--execute", action="store_true", help="실제 주문 (없으면 드라이런)")
    trade.add_argument("--once", choices=["kr", "us"], help="대기 없이 지정 시장 1회만 실행")
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return
    if args.command == "analyze":
        analyze()
        return

    if args.once:
        try:
            run_once(args.once, args.execute)
        except OrderUncertainError as exc:
            log(f"[주문 확인 필요] {exc} 남은 주문은 보내지 않았습니다.")
        return

    log(f"포트폴리오 루프 시작 ({'실제 주문' if args.execute else '드라이런'})")
    tries = {}  # (시장, 현지 날짜) -> 시도 횟수. 성공 시 MAX_TRIES로 채워 중복 실행 방지

    while True:
        for market, cfg in MARKETS.items():
            now = datetime.now(cfg["tz"])
            day_key = (market, now.strftime("%Y-%m-%d"))
            in_window = cfg["start"] <= now.strftime("%H:%M") < cfg["end"]

            if now.weekday() < 5 and in_window and tries.get(day_key, 0) < MAX_TRIES:
                tries[day_key] = tries.get(day_key, 0) + 1
                try:
                    run_once(market, args.execute)
                    tries[day_key] = MAX_TRIES
                except OrderUncertainError as exc:
                    tries[day_key] = MAX_TRIES  # 중복 주문 방지: 오늘 이 시장은 재시도 안 함
                    log(f"[{market.upper()} 주문 확인 필요] {exc} 남은 주문은 보내지 않았고, 오늘은 재시도하지 않습니다.")
                except Exception as exc:
                    log(f"[{market.upper()} 오류 {tries[day_key]}/{MAX_TRIES}] {exc}")

        time.sleep(30)


if __name__ == "__main__":
    main()
