"""
파일명: main.py
역할: 국내 및 해외주식 자동매매 프로그램의 실행 흐름을 제어하고 API 동작을 검증하는 메인 파일
"""

import json
import time

# 인증 모듈에서 토큰 발급 함수 가져오기
from kis_auth import issue_access_token

# 국내/해외 주식 모듈을 별칭(Alias)을 사용하여 임포트 (함수명 충돌 방지)
import kis_domestic_stock as domestic
import kis_overseas_stock as overseas


# =========================================================
# 공통 출력 함수
# =========================================================
def print_result(title: str, data: dict) -> None:
    """
    API 응답 결과를 콘솔 창에 보기 좋게 정렬하여 출력합니다.
    
    :param title: 출력할 테스트 항목의 제목
    :param data: 한국투자증권 Open API가 반환한 JSON(dict) 데이터
    """
    print(f"\n========== {title} ==========")
    print(f"응답 코드 : {data.get('rt_cd')}")  # rt_cd가 0이면 성공, 그 외는 실패
    print(f"메시지    : {data.get('msg1')}")   # 서버에서 보내준 상세 메시지

    # JSON 데이터를 들여쓰기(indent=2) 처리하여 가독성 높게 출력
    print(json.dumps(data, ensure_ascii=False, indent=2))


# =========================================================
# 국내주식 API 테스트 시나리오
# =========================================================
def domestic_test(token: str) -> None:
    """
    국내주식 관련 API 기능들을 순차적으로 검증합니다.
    """
    print("\n=========================================================")
    print(">>> [1] 국내주식 API 테스트 시작")
    print("=========================================================")
    
    # 테스트 종목: 삼성전자 (6자리 종목코드)
    stock_code = "005930"

    # 1. 국내 현재가 조회
    price_data = domestic.inquire_price(token, stock_code)
    print_result("국내 현재가 조회", price_data)
    time.sleep(1.0)  # 과도한 API 호출로 인한 당사 규제(초당 호출 제한) 방지

    # 2. 국내 매수 주문 (실제 돈이 나가므로 테스트할 때만 아래 주석을 해제하세요)
    # buy_result = domestic.order_stock(
    #      token=token,
    #      order_type="buy",
    #      stock_code=stock_code,
    #      quantity=1,
    #      price=70000,
    # )
    # print_result("국내 현금 매수 주문", buy_result)
    # time.sleep(1.0)

    # 3. 국내 당일 주문/체결 내역 조회
    order_history = domestic.inquire_order_history(token)
    print_result("국내 주문/체결 조회", order_history)
    time.sleep(1.0)

    # 4. 국내 당일 미체결 주문 조회 (필요 시 주석 해제)
    # unfilled = domestic.inquire_unfilled_orders(token)
    # print_result("국내 미체결 조회", unfilled)
    # time.sleep(1.0)

    # 5. 국내 계좌 잔고 및 보유 종목 조회
    balance = domestic.inquire_balance(token)
    print_result("국내 잔고 조회", balance)


# =========================================================
# 해외주식 API 테스트 시나리오
# =========================================================
def overseas_test(token: str) -> None:
    """
    해외주식(미국) 관련 API 기능들을 순차적으로 검증합니다.
    """
    print("\n=========================================================")
    print(">>> [2] 해외주식 API 테스트 시작")
    print("=========================================================")
    
    # 테스트 종목: 애플 (AAPL)
    # 한투 API 특성상 시세 조회용 거래소 코드와 주문용 거래소 코드가 다릅니다.
    market_price = "NAS"   # 시세 조회용 시장코드 (NAS: 나스닥)
    market_order = "NASD"  # 주문 전송용 시장코드 (NASD: 나스닥)
    ticker = "AAPL"        # 종목 심볼(티커)

    # 1. 해외 현재가 조회
    price_data = overseas.inquire_price(token, market_price, ticker)
    print_result("해외 현재가 조회", price_data)
    time.sleep(1.0)  # 초당 호출 제한(트래픽 제어)을 위한 휴식

    # 2. 해외 매수 주문 (실제 달러 자산이 사용되므로 테스트 시에만 주석을 해제하세요)
    # buy_result = overseas.order_stock(
    #     token=token,
    #     order_type="buy",
    #     market_code=market_order,
    #     ticker=ticker,
    #     quantity=1,
    #     price=180.50,  # 해외주식은 소수점 단가 주문이 가능하므로 float 전달 가능
    # )
    # print_result("해외 해외 지정가 매수 주문", buy_result)
    # time.sleep(1.0)

    # 3. 해외 당일 주문/체결 내역 조회
    order_history = overseas.inquire_order_history(token)
    print_result("해외 주문/체결 조회", order_history)
    time.sleep(1.0)

    # 4. 해외 당일 미체결 주문 조회 (필요 시 주석 해제)
    # unfilled = overseas.inquire_unfilled_orders(token)
    # print_result("해외 미체결 조회", unfilled)
    # time.sleep(1.0)

    # 5. 해외 계좌 자산 및 외화 잔고 조회
    balance = overseas.inquire_balance(token)
    print_result("해외 잔고 및 자산 조회", balance)


# =========================================================
# 프로그램 시작점 (Main Controller)
# =========================================================
def main() -> None:
    """
    Access Token을 통합 발급받은 후, 
    국내주식 및 해외주식 테스트 시나리오를 컨트롤합니다.
    """
    # 1. 공통 Access Token 발급 (만료 시 내부 캐시에서 자동 갱신됨)
    token = issue_access_token()

    # 2. 국내주식 매매 프로세스 테스트
    domestic_test(token)
    time.sleep(1.5)  # 국내와 해외 테스트 사이의 여유 시간 확보

    # 3. 해외주식 매매 프로세스 테스트
    overseas_test(token)


if __name__ == "__main__":
    # 이 파일이 본래 목적으로 실행될 때만 main()을 수행 (외부 모듈 import 시 자동 실행 방지)[cite: 7]
    main()