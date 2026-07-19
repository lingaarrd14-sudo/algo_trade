"""
파일명: main.py
역할: 정해진 시간에 삼성전자와 애플을 시장가로 매수/매도하는 자동매매 실행 파일
"""

import json
import time
from datetime import datetime

# 인증 모듈에서 Access Token 발급 함수 가져오기
from kis_auth import issue_access_token

# 국내/해외 주식 모듈을 별칭으로 임포트
import kis_domestic_stock as domestic
import kis_overseas_stock as overseas


# =========================================================
# 공통 출력 함수
# =========================================================
def print_result(title: str, data: dict) -> None:
    """
    API 응답 결과를 콘솔에 보기 좋게 출력합니다.

    :param title: 출력 제목
    :param data: 한국투자증권 Open API가 반환한 JSON(dict) 응답
    """
    print(f"\n========== {title} ==========")
    print(f"응답 코드 : {data.get('rt_cd')}")
    print(f"메시지    : {data.get('msg1')}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# =========================================================
# 국내주식 주문 실행 함수
# =========================================================
def execute_domestic_order(token: str, order_type: str, stock_code: str, quantity: int) -> None:
    """
    국내주식 주문 1회를 실행하고, 주문 전후 상태를 함께 조회합니다.

    :param token: 유효한 Access Token
    :param order_type: 주문 종류 ('buy' 또는 'sell')
    :param stock_code: 국내주식 6자리 종목코드
    :param quantity: 주문 수량
    """
    side_name = "매수" if order_type == "buy" else "매도"

    price_data = domestic.inquire_price(token, stock_code)
    print_result(f"국내 현재가 조회 ({stock_code})", price_data)
    time.sleep(1.0)

    order_result = domestic.order_stock(
        token=token,
        order_type=order_type,
        stock_code=stock_code,
        quantity=quantity,
    )
    print_result(f"국내 시장가 {side_name} 주문", order_result)
    time.sleep(1.0)

    order_history = domestic.inquire_order_history(token)
    print_result("국내 주문/체결 조회", order_history)
    time.sleep(1.0)

    unfilled = domestic.inquire_unfilled_orders(token)
    print_result("국내 미체결 조회", unfilled)
    time.sleep(1.0)

    balance = domestic.inquire_balance(token)
    print_result("국내 잔고 조회", balance)


# =========================================================
# 해외주식 주문 실행 함수
# =========================================================
def execute_overseas_order(
    token: str,
    order_type: str,
    market_price_code: str,
    market_order_code: str,
    ticker: str,
    quantity: int,
) -> None:
    """
    해외주식 주문 1회를 실행하고, 주문 전후 상태를 함께 조회합니다.

    :param token: 유효한 Access Token
    :param order_type: 주문 종류 ('buy' 또는 'sell')
    :param market_price_code: 시세 조회용 거래소 코드 (예: NAS)
    :param market_order_code: 주문 전송용 거래소 코드 (예: NASD)
    :param ticker: 해외 종목 티커
    :param quantity: 주문 수량
    """
    side_name = "매수" if order_type == "buy" else "매도"

    price_data = overseas.inquire_price(token, market_price_code, ticker)
    print_result(f"해외 현재가 조회 ({ticker})", price_data)
    time.sleep(1.0)

    order_result = overseas.order_stock(
        token=token,
        order_type=order_type,
        market_code=market_order_code,
        ticker=ticker,
        quantity=quantity,
    )
    print_result(f"해외 시장가 {side_name} 주문", order_result)
    time.sleep(1.0)

    order_history = overseas.inquire_order_history(token)
    print_result("해외 주문/체결 조회", order_history)
    time.sleep(1.0)

    unfilled = overseas.inquire_unfilled_orders(token)
    print_result("해외 미체결 조회", unfilled)
    time.sleep(1.0)

    balance = overseas.inquire_balance(token)
    print_result("해외 잔고 및 자산 조회", balance)


# =========================================================
# 자동매매 스케줄러
# =========================================================
def main() -> None:
    """
    평일 기준으로 지정된 시간에 시장가 주문을 1회씩 실행합니다.

    - 국내: 삼성전자 매수/매도
    - 해외: 애플 매수/매도
    """
    # 국내 주문 설정
    samsung_code = "005930"
    samsung_quantity = 1

    # 해외 주문 설정
    apple_price_market_code = "NAS"
    apple_order_market_code = "NASD"
    apple_ticker = "AAPL"
    apple_quantity = 1

    # 주문 실행 시간 (서버 로컬 시간 기준)
    domestic_buy_time = "09:05"
    domestic_sell_time = "15:20"
    overseas_buy_time = "22:35"
    overseas_sell_time = "04:55"

    # 프로세스 실행 중 같은 날짜에 같은 주문이 중복 실행되는 것을 방지
    ran = set()

    print("자동매매 스케줄러 시작")
    print(f"국내: {domestic_buy_time} 삼성전자 매수, {domestic_sell_time} 삼성전자 매도")
    print(f"해외: {overseas_buy_time} 애플 매수, {overseas_sell_time} 애플 매도")

    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")
        weekday = now.weekday()  # 월=0, 금=4, 토=5, 일=6

        try:
            # 평일 낮: 삼성전자 시장가 매수
            if weekday < 5 and current_time == domestic_buy_time and (today, "domestic_buy") not in ran:
                token = issue_access_token()
                execute_domestic_order(
                    token=token,
                    order_type="buy",
                    stock_code=samsung_code,
                    quantity=samsung_quantity,
                )
                ran.add((today, "domestic_buy"))

            # 평일 낮: 삼성전자 시장가 매도
            if weekday < 5 and current_time == domestic_sell_time and (today, "domestic_sell") not in ran:
                token = issue_access_token()
                execute_domestic_order(
                    token=token,
                    order_type="sell",
                    stock_code=samsung_code,
                    quantity=samsung_quantity,
                )
                ran.add((today, "domestic_sell"))

            # 평일 밤: 애플 시장가 매수
            if weekday < 5 and current_time == overseas_buy_time and (today, "overseas_buy") not in ran:
                token = issue_access_token()
                execute_overseas_order(
                    token=token,
                    order_type="buy",
                    market_price_code=apple_price_market_code,
                    market_order_code=apple_order_market_code,
                    ticker=apple_ticker,
                    quantity=apple_quantity,
                )
                ran.add((today, "overseas_buy"))

            # 화~토 새벽: 전날 밤 미국장 매수분 애플 시장가 매도
            if 1 <= weekday <= 5 and current_time == overseas_sell_time and (today, "overseas_sell") not in ran:
                token = issue_access_token()
                execute_overseas_order(
                    token=token,
                    order_type="sell",
                    market_price_code=apple_price_market_code,
                    market_order_code=apple_order_market_code,
                    ticker=apple_ticker,
                    quantity=apple_quantity,
                )
                ran.add((today, "overseas_sell"))

        except Exception as exc:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 오류: {exc}")

        # 분 단위 스케줄 확인용 대기 시간
        time.sleep(20)


if __name__ == "__main__":
    main()
