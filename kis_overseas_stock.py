"""
파일명: kis_overseas_stock.py
역할: 해외주식(미국 주식 중심) 거래와 관련된 조회, 주문, 체결, 잔고 API 기능을 담당하는 모듈
"""

import kis_config
import kis_client

# ↓ 26.07.05 추가: 해외 주문/체결 조회 함수가 오늘 날짜를 정상적으로 보내도록 날짜 모듈 추가
from datetime import datetime

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


def order_stock(token: str, order_type: str, market_code: str, ticker: str, quantity: int, price: float = 0) -> dict:
    """
    해외주식 지정을 현금 매수 또는 매도 주문합니다.
    
    :param order_type: 주문 종류 ('buy' 또는 'sell')
    :param market_code: 주문용 거래소 코드 (NASD: 나스닥, NYSE: 뉴욕, AMEX: 아멕스)
    :param ticker: 해외 종목 심볼 기호
    :param quantity: 주문 수량
    :param price: 주문 단가 (시장가 주문에서는 사용하지 않음)
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
        "OVRS_ORD_UNPR": "0",          # 시장가 주문은 단가 0
        "ORD_SVR_DVSN_CD": "0",        # 주문서버구분코드
        "ORD_DVSN": "01",              # 01: 시장가 주문
    }
    return kis_client.post_order(
        endpoint=kis_config.OVERSEAS_ORDER_ENDPOINT,
        tr_id=tr_id,
        token=token,
        body=body,
    )

def inquire_order_history(token: str, filled: str = "00") -> dict:
    """
    오늘 발생한 해외주식의 전체 주문 내역 및 체결 상태를 상세히 조회합니다.
    실전 전환 시 미체결 수정 필요
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
        "CCLD_NCCS_DVSN": filled,                        # 체결미체결구분 (00: 전체, 01: 체결, 02: 미체결) - 모의투자는 "00"만 가능
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

def handle_unfilled_orders(token: str) -> None:
    """
    해외주식 미체결 주문을 조회하고,
    1. 기존 미체결 주문 취소
    2. 미체결 잔량만큼 신규 시장가 주문
    """
    response = inquire_order_history(token, "02")

    if str(response.get("rt_cd", "")) != "0":
        print(
            "[해외 미체결 조회 실패]",
            response.get("msg_cd", ""),
            response.get("msg1", ""),
        )
        return

    rows = response.get("output1", [])
    if isinstance(rows, dict):
        rows = [rows]

    for row in rows:
        ticker = str(row.get("pdno", "")).strip()
        order_no = str(row.get("odno", "")).strip()

        if not ticker or not order_no:
            continue

        # 미체결수량
        qty_text = str(
            row.get("nccs_qty", "")
        ).replace(",", "").strip()

        if qty_text:
            try:
                remaining_qty = int(float(qty_text))
            except ValueError:
                continue
        else:
            try:
                order_qty = int(float(
                    str(
                        row.get(
                            "ft_ord_qty",
                            row.get("ord_qty", "0"),
                        )
                    ).replace(",", "") or 0
                ))

                filled_qty = int(float(
                    str(
                        row.get(
                            "ft_ccld_qty",
                            row.get("tot_ccld_qty", "0"),
                        )
                    ).replace(",", "") or 0
                ))

                remaining_qty = max(order_qty - filled_qty, 0)

            except ValueError:
                continue

        if remaining_qty <= 0:
            continue

        market_code = str(
            row.get("ovrs_excg_cd", "NASD")
        ).strip() or "NASD"

        side_code = str(
            row.get(
                "sll_buy_dvsn_cd",
                row.get("sll_buy_dvsn", ""),
            )
        ).strip()

        if side_code == "02":
            order_type = "buy"
        elif side_code == "01":
            order_type = "sell"
        else:
            print(f"[매수/매도 구분 실패] {ticker}")
            continue

        # 미국 모의투자 기준
        tr_id = (
            kis_config.OVERSEAS_REVISE_CANCEL_TR_ID_PAPER
            if kis_config.is_paper()
            else kis_config.OVERSEAS_REVISE_CANCEL_TR_ID_REAL
        )

        # 1. 기존 주문 취소
        cancel_body = {
            "CANO": kis_config.ACCOUNT_NO,
            "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
            "OVRS_EXCG_CD": market_code,
            "PDNO": ticker,
            "ORGN_ODNO": order_no,

            "RVSE_CNCL_DVSN_CD": "02",  # 취소
            "ORD_QTY": str(remaining_qty),
            "OVRS_ORD_UNPR": "0",

            "MGCO_APTM_ODNO": "",
            "ORD_SVR_DVSN_CD": "0",
        }

        cancel_result = kis_client.post_order(
            endpoint=kis_config.OVERSEAS_REVISE_CANCEL_ENDPOINT,
            tr_id=tr_id,
            token=token,
            body=cancel_body,
        )

        if str(cancel_result.get("rt_cd", "")) != "0":
            print(
                f"[취소 실패] {ticker} / "
                f"{order_no} / "
                f"{cancel_result.get('msg_cd', '')} / "
                f"{cancel_result.get('msg1', '')}"
            )
            continue

        print(
            f"[취소 성공] {ticker} / "
            f"{remaining_qty}주"
        )

        # 2. 취소 성공한 경우에만 신규 시장가 주문
        order_result = order_stock(
            token=token,
            order_type=order_type,
            market_code=market_code,
            ticker=ticker,
            quantity=remaining_qty,
        )

        if str(order_result.get("rt_cd", "")) == "0":
            print(
                f"[시장가 재주문 성공] "
                f"{ticker} / {remaining_qty}주"
            )
        else:
            print(
                f"[시장가 재주문 실패] "
                f"{ticker} / {remaining_qty}주 / "
                f"{order_result.get('msg_cd', '')} / "
                f"{order_result.get('msg1', '')}"
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

def inquire_position_amount(token: str) -> dict:
    """모의투자용 해외주식 예수금 조회 함수, 매수가능금액조회 api를 우회"""
    tr_id = kis_config.OVERSEAS_POSITION_AMOUNT_TR_ID_PAPER

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "OVRS_EXCG_CD": "NASD",        # 미국 통합 조회를 위해 사용
        "OVRS_ORD_UNPR": "30.0",           # 거래 통화 기준 코드 (미국 주식은 USD)
        "ITEM_CD": "AAPL",          # 조회용 임의 종목코드 (실제 잔고와 무관)
    }
    return kis_client.get(
        endpoint=kis_config.OVERSEAS_POSITION_AMOUNT_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )
