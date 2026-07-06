"""
파일명: kis_domestic_stock.py
역할: 국내주식 거래와 관련된 조회, 주문, 체결, 잔고 API 기능을 담당하는 모듈
"""

from datetime import datetime
import kis_config
import kis_client

def today_yyyymmdd() -> str:
    """오늘 날짜를 KIS API 규격인 YYYYMMDD 형태의 문자열로 반환합니다."""
    return datetime.now().strftime("%Y%m%d")


def inquire_price(token: str, stock_code: str) -> dict:
    """
    국내주식의 현재가 정보를 상세히 조회합니다.
    
    :param token: 유효한 Access Token
    :param stock_code: 국내주식 6자리 종목코드 (예: '005930')
    """
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",  # J: 주식, ETF, ETN 공통 데이터 구분자
        "FID_INPUT_ISCD": stock_code,    # 종목코드
    }
    return kis_client.get(
        endpoint=kis_config.DOMESTIC_PRICE_ENDPOINT,
        tr_id=kis_config.DOMESTIC_PRICE_TR_ID,
        token=token,
        params=params,
    )


def order_stock(token: str, order_type: str, stock_code: str, quantity: int, price: int = 0) -> dict:
    """
    국내주식 지정을 현금 매수 또는 매도 주문합니다.
    
    :param order_type: 주문 종류 ('buy' 또는 'sell')
    :param stock_code: 국내주식 6자리 종목코드
    :param quantity: 주문 수량
    :param price: 주문 단가 (시장가 주문에서는 사용하지 않음)
    """
    # 환경(모의/실전)과 매수/매도 여부에 따른 정확한 TR_ID 선택
    if order_type == "buy":
        tr_id = kis_config.DOMESTIC_BUY_TR_ID_PAPER if kis_config.is_paper() else kis_config.DOMESTIC_BUY_TR_ID_REAL
    elif order_type == "sell":
        tr_id = kis_config.DOMESTIC_SELL_TR_ID_PAPER if kis_config.is_paper() else kis_config.DOMESTIC_SELL_TR_ID_REAL
    else:
        raise ValueError("order_type은 오직 'buy' 또는 'sell'만 가능합니다.")

    # 한국투자증권 국내주식 주문 표준 Body 데이터 포맷
    body = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "PDNO": stock_code,
        "ORD_DVSN": "01",              # 01: 시장가 주문
        "ORD_QTY": str(quantity),      # 수량은 반드시 문자열로 전송
        "ORD_UNPR": "0",               # 시장가 주문은 단가 0
        "EXCG_ID_DVSN_CD": "KRX",      # 한국거래소 표준 코드
        "SLL_TYPE": "",                # 공매도 유형 (일반 유저 필수 공백)
        "CNDT_PRIC": "",               # 조건부 가격 구분 (일반 유저 필수 공백)
    }
    return kis_client.post_order(
        endpoint=kis_config.DOMESTIC_ORDER_ENDPOINT,
        tr_id=tr_id,
        token=token,
        body=body,
    )


def inquire_order_history(token: str) -> dict:
    """오늘 발생한 국내주식의 전체 주문 및 체결 내역을 조회합니다."""
    today = today_yyyymmdd()
    tr_id = kis_config.DOMESTIC_ORDER_HISTORY_TR_ID_PAPER if kis_config.is_paper() else kis_config.DOMESTIC_ORDER_HISTORY_TR_ID_REAL

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "INQR_STRT_DT": today,         # 조회 시작일
        "INQR_END_DT": today,           # 조회 종료일 (당일 매매 추적)
        "SLL_BUY_DVSN_CD": "00",       # 00: 전체, 01: 매도, 02: 매수
        "INQR_DVSN": "00",            # 00: 전체역사 조회
        "PDNO": "",                    # 특정 종목만 지정하려면 코드 입력, 비워두면 계좌 전체
        "CCLD_DVSN": "00",            # 00: 전체, 01: 체결, 02: 미체결
        "ORD_GNO_BRNO": "",            # 지점번호 (공백 유지)
        "ODNO": "",                    # 특정 주문번호만 조회 시 입력
        "INQR_DVSN_3": "00",           # 00: 전체
        "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "",          # 연속조회 키 (첫 페이지 요청 시 공백)
        "CTX_AREA_NK100": "",          # 연속조회 키 (첫 페이지 요청 시 공백)
        "EXCG_ID_DVSN_CD": "KRX",
    }
    return kis_client.get(
        endpoint=kis_config.DOMESTIC_ORDER_HISTORY_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )


def inquire_unfilled_orders(token: str) -> dict:
    """오늘 아직 체결되지 않고 대수 중인 국내주식 미체결 주문 내역만 조회합니다."""
    today = today_yyyymmdd()
    tr_id = kis_config.DOMESTIC_ORDER_HISTORY_TR_ID_PAPER if kis_config.is_paper() else kis_config.DOMESTIC_ORDER_HISTORY_TR_ID_REAL

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "INQR_STRT_DT": today,
        "INQR_END_DT": today,
        "SLL_BUY_DVSN_CD": "00",
        "INQR_DVSN": "00",
        "PDNO": "",
        "CCLD_DVSN": "02",            # ★ 02로 설정하여 '미체결' 상태만 필터링합니다.
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
        "EXCG_ID_DVSN_CD": "KRX",
    }
    return kis_client.get(
        endpoint=kis_config.DOMESTIC_ORDER_HISTORY_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )


def inquire_balance(token: str) -> dict:
    """국내주식 계좌의 예수금 및 현재 보유 종목 현황(수익률, 평가금액 등)을 조회합니다."""
    tr_id = kis_config.DOMESTIC_BALANCE_TR_ID_PAPER if kis_config.is_paper() else kis_config.DOMESTIC_BALANCE_TR_ID_REAL

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "AFHR_FLPR_YN": "N",           # 시간외단일가 시간 평가지표 포함 여부 (N: 포함안함)
        "OFL_YN": "",                  # 오프라인 잔고 포함 여부
        "INQR_DVSN": "02",            # 02: 종목별 잔고 현황 조회
        "UNPR_DVSN": "01",            # 01: 단가 구분 (평균단가 기준)
        "FUND_STTL_ICLD_YN": "N",     # 펀드결제 기준 포함 여부
        "FNCG_AMT_AUTO_RDPT_YN": "N", # 융자금액 자동상환 여부
        "PRCS_DVSN": "00",            # 00: 일반 처리
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }
    return kis_client.get(
        endpoint=kis_config.DOMESTIC_BALANCE_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )
