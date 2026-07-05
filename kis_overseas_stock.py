"""
파일명: kis_overseas_stock.py
역할: 해외주식(미국 주식 중심) 거래와 관련된 조회, 주문, 체결, 잔고 API 기능을 담당하는 모듈
"""

import kis_config
import kis_client

# ↓ 26.07.05 추가: 해외 주문/체결 조회 함수가 오늘 날짜를 정상적으로 보내도록 날짜 모듈 추가
from datetime import datetime
import kis_config
import kis_client

def inquire_price(token: str, market_code: str, ticker: str) -> dict:
    """
    해외주식의 실시간/지연 현재 시세 및 호가 정보를 조회합니다.
    
    :param token: 유효한 Access Token
    :param market_code: 시세 조회용 거래소 코드 (NAS: 나스닥, NYS: 뉴욕, AMS: 아멕스)
    :param ticker: 해외 종목 심볼 기호 (예: 'AAPL', 'TSLA', 'NVDA')
    """
    params = {
        "AUTH_CODE": "",               # 기본 공백 유지
        "EXCD": market_code,           # 해외 거래소 코드
        "SYMB": ticker,                # 종목 티커 심볼
    }
    return kis_client.get(
        endpoint=kis_config.OVERSEAS_PRICE_ENDPOINT,
        tr_id=kis_config.OVERSEAS_PRICE_TR_ID,
        token=token,
        params=params,
    )


def order_stock(token: str, order_type: str, market_code: str, ticker: str, quantity: int, price: float) -> dict:
    """
    해외주식 지정을 현금 매수 또는 매도 주문합니다.
    
    :param order_type: 주문 종류 ('buy' 또는 'sell')
    :param market_code: 주문용 거래소 코드 (NASD: 나스닥, NYSE: 뉴욕, AMEX: 아멕스)
    :param ticker: 해외 종목 심볼 기호
    :param quantity: 주문 수량
    :param price: 주문 단가 (float 타입을 지원하여 달러 소수점 입력 가능)
    """
    # 환경(모의/실전)과 매수/매도 여부에 따른 정확한 해외 TR_ID 선택
    if order_type == "buy":
        tr_id = kis_config.OVERSEAS_BUY_TR_ID_PAPER if kis_config.is_paper() else kis_config.OVERSEAS_BUY_TR_ID_REAL
    elif order_type == "sell":
        tr_id = kis_config.OVERSEAS_SELL_TR_ID_PAPER if kis_config.is_paper() else kis_config.OVERSEAS_SELL_TR_ID_REAL
    else:
        raise ValueError("order_type은 오직 'buy' 또는 'sell'만 가능합니다.")

    # 한국투자증권 해외주식 주문 표준 Body 데이터 포맷
    body = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "OVRS_EXCG_CD": market_code,   # 주문용 거래소 코드 (주의: 시세용과 다름)
        "PDNO": ticker,                # 종목 티커
        "ORD_QTY": str(quantity),      # 수량 문자열
        "ORD_UNPR": f"{price:.2f}",    # 해외주식 소수점 매매를 고려해 둘째자리까지 포맷팅 후 문자열화
        "ORD_DVSN": "00",              # 00: 지정가 주문
    }
    return kis_client.post_order(
        endpoint=kis_config.OVERSEAS_ORDER_ENDPOINT,
        tr_id=tr_id,
        token=token,
        body=body,
    )

# ↓ 26.07.05 추가: 오늘날짜 생성 추가, 필수 날짜 파라미터 입력
def inquire_order_history(token: str) -> dict:
    """
    오늘 발생한 해외주식의 전체 주문 내역 및 체결 상태를 상세히 조회합니다.
    (API: 해외주식 주문체결내역 조회 - TTTS3035R / VTTS3035R)
    """
    # 현재 환경(모의투자/실전투자)에 맞추어 적절한 거래 ID(TR_ID)를 자동으로 선택합니다.
    tr_id = kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_PAPER if kis_config.is_paper() else kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_REAL

    # 조회에 필요한 시작일과 종료일을 지정하기 위해 오늘 날짜를 YYYYMMDD 형태로 생성합니다.
    today = datetime.now().strftime("%Y%m%d")

    params = {
        # 1. 계좌 기본 정보
        "CANO": kis_config.ACCOUNT_NO,                 # 종합계좌번호 (앞 8자리)
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE, # 계좌상품코드 (일반적으로 '01')
        
        # 2. 조회 필터링 정보
        "PDNO": "",                                    # 특정 종목코드(티커). 공백("") 기입 시 계좌 내 전 종목 조회
        "ORD_STRT_DT": today,                          # 조회 시작일자 (YYYYMMDD 형식, 현지시각 기준)
        "ORD_END_DT": today,                           # 조회 종료일자 (YYYYMMDD 형식, 현지시각 기준)
        "SLL_BUY_DVSN": "00",                          # 매도매수구분 (00: 전체, 01: 매도, 02: 매수)
        "CCLD_NCCS_DVSN": "00",                        # 체결미체결구분 (00: 전체, 01: 체결, 02: 미체결) - 모의투자는 "00"만 가능
        "OVRS_EXCG_CD": "NASD",                        # 해외거래소코드 (미국 시장 전체를 통합 조회할 때 주로 'NASD' 사용)
        
        # 3. 정렬 및 특정 주문 지정 정보
        "SORT_SQN": "DS",                              # 정렬순서 (DS: 내림차순-최신순, AS: 오름차순-과거순)
        "ORD_DT": "",                                  # 특정 주문일자 (기간 조회 시 공백 유지)
        "ORD_GNO_BRNO": "",                            # 주문지점번호 (일반 사용자는 공백 유지)
        "ODNO": "",                                    # 특정 원주문번호 (특정 주문 1건만 조회할 때 입력, 평소엔 공백)
        
        # 4. 페이징(연속조회) 처리 정보
        "CTX_AREA_NK200": "",                          # 연속조회 키 1 (첫 페이지 조회 시 공백 기입)
        "CTX_AREA_FK200": "",                          # 연속조회 키 2 (첫 페이지 조회 시 공백 기입)
    }
    
    return kis_client.get(
        endpoint=kis_config.OVERSEAS_ORDER_HISTORY_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )


def inquire_unfilled_orders(token: str) -> dict:
    """오늘 보낸 해외 주문 중 아직 완전히 체결되지 않고 남아있는 미체결 계약만 조회합니다."""
    tr_id = kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_PAPER if kis_config.is_paper() else kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_REAL

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "OVRS_EXCG_CD": "NASD",
        "SLL_BUY_DVSN_CD": "00",
        "INQR_DVSN": "02",            # ★ 02로 세팅하여 미체결 항목만 쏙 골라냅니다.
        "PDNO": "",
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": "",
    }
    return kis_client.get(
        endpoint=kis_config.OVERSEAS_ORDER_HISTORY_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )


def inquire_balance(token: str) -> dict:
    """해외주식 계좌에 보유 중인 해외 자산 현황과 통화별 외화(달러 등) 평가 금액을 조회합니다."""
    tr_id = kis_config.OVERSEAS_BALANCE_TR_ID_PAPER if kis_config.is_paper() else kis_config.OVERSEAS_BALANCE_TR_ID_REAL

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "OVRS_EXCG_CD": "NASD",        # 미국 통합 조회를 위해 사용
        "TR_CRCY_CD": "USD",           # 거래 통화 기준 코드 (미국 주식은 USD)
        "CTX_AREA_FK200": "",
        "CTX_AREA_NK200": "",
    }
    return kis_client.get(
        endpoint=kis_config.OVERSEAS_BALANCE_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )