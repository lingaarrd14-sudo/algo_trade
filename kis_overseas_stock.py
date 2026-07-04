"""
파일명: kis_overseas_stock.py
역할: 해외주식(미국 주식 중심) 거래와 관련된 조회, 주문, 체결, 잔고 API 기능을 담당하는 모듈
"""

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


def inquire_order_history(token: str) -> dict:
    """오늘 발생한 해외주식의 전체 주문 내역 및 체결 상태를 상세히 조회합니다."""
    tr_id = kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_PAPER if kis_config.is_paper() else kis_config.OVERSEAS_ORDER_HISTORY_TR_ID_REAL

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "OVRS_EXCG_CD": "NASD",        # 미국 시장 통합 조회 관례로 주로 'NASD' 사용
        "SLL_BUY_DVSN_CD": "00",       # 00: 전체 조회 (01:매도, 02:매수)
        "INQR_DVSN": "00",            # 00: 전체 내역 필터링
        "PDNO": "",                    # 특정 종목 지정 시 입력, 공백 시 계좌 전체
        "CTX_AREA_FK200": "",          # 연속조회 키 (첫 페이지 공백)
        "CTX_AREA_NK200": "",          # 연속조회 키 (첫 페이지 공백)
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