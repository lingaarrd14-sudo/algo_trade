import json
import time
from kis_auth import issue_access_token
from kis_domestic_stock import (
    inquire_price,
    order_stock,
    inquire_order_history,
    inquire_unfilled_orders,
    inquire_balance,
)

# =========================================================
# 실행 예제
# =========================================================

def print_result(title: str, data: dict) -> None:
    """API 응답을 콘솔에서 보기 좋게 출력한다."""
    print(f"\n========== {title} ==========")
    print(f"응답 코드: {data.get('rt_cd')}")
    print(f"메시지: {data.get('msg1')}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    """토큰 발급 후 현재가, 주문 내역, 미체결, 잔고를 순서대로 조회한다."""
    token = issue_access_token()

    # 삼성전자 종목 코드
    stock_code = "005930"

    price_data = inquire_price(token, stock_code)
    print_result("현재가 조회", price_data)
    time.sleep(1.0)

    # 주문 테스트가 필요할 때만 주석 해제
    buy_result = order_stock(
         token=token,
         order_type="buy",
         stock_code=stock_code,
         quantity=1,
         price=70000,
    )
    print_result("매수 주문", buy_result)
    time.sleep(1.0)

    order_history = inquire_order_history(token)
    print_result("주문/체결 조회", order_history)

    #unfilled = inquire_unfilled_orders(token)
    #print_result("미체결 조회", unfilled)

    balance = inquire_balance(token)
    print_result("잔고 조회", balance)


if __name__ == "__main__":
    main()
