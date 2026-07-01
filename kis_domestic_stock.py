from datetime import datetime
import kis_config
import kis_client

# =========================================================
# 국내주식 API
# =========================================================

def today_yyyymmdd() -> str:
    """오늘 날짜를 KIS API 요청 형식(YYYYMMDD)으로 반환한다."""
    return datetime.now().strftime("%Y%m%d")


def inquire_price(token: str, stock_code: str) -> dict:
    """국내주식 현재가를 조회한다."""
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }

    return kis_client.get(
        endpoint=kis_config.PRICE_ENDPOINT,
        tr_id=kis_config.PRICE_TR_ID,
        token=token,
        params=params,
    )


def order_stock(
    token: str,
    order_type: str,
    stock_code: str,
    quantity: int,
    price: int,
) -> dict:
    """국내주식을 현금 매수 또는 매도 주문한다."""
    if order_type == "buy":
        tr_id = kis_config.BUY_TR_ID_PAPER if kis_config.is_paper() else kis_config.BUY_TR_ID_REAL
    elif order_type == "sell":
        tr_id = kis_config.SELL_TR_ID_PAPER if kis_config.is_paper() else kis_config.SELL_TR_ID_REAL
    else:
        raise ValueError("order_type은 'buy' 또는 'sell'이어야 합니다.")

    # ORD_DVSN "00"은 지정가 주문을 의미한다.
    body = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "PDNO": stock_code,
        "ORD_DVSN": "00",
        "ORD_QTY": str(quantity),
        "ORD_UNPR": str(price),
        "EXCG_ID_DVSN_CD": "KRX",
        "SLL_TYPE": "",
        "CNDT_PRIC": "",
    }

    return kis_client.post_order(
        endpoint=kis_config.ORDER_ENDPOINT,
        tr_id=tr_id,
        token=token,
        body=body,
    )


def inquire_order_history(token: str) -> dict:
    """오늘 주문 및 체결 내역을 조회한다."""
    today = today_yyyymmdd()

    tr_id = (
        kis_config.ORDER_HISTORY_TR_ID_PAPER
        if kis_config.is_paper()
        else kis_config.ORDER_HISTORY_TR_ID_REAL
    )

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "INQR_STRT_DT": today,
        "INQR_END_DT": today,
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

    return kis_client.get(
        endpoint=kis_config.ORDER_HISTORY_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )


def inquire_unfilled_orders(token: str) -> dict:
    """오늘 미체결 주문만 조회한다."""
    today = today_yyyymmdd()

    tr_id = (
        kis_config.ORDER_HISTORY_TR_ID_PAPER
        if kis_config.is_paper()
        else kis_config.ORDER_HISTORY_TR_ID_REAL
    )

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "INQR_STRT_DT": today,
        "INQR_END_DT": today,
        "SLL_BUY_DVSN_CD": "00",
        "INQR_DVSN": "00",
        "PDNO": "",
        "CCLD_DVSN": "02",
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
        "EXCG_ID_DVSN_CD": "KRX",
    }

    return kis_client.get(
        endpoint=kis_config.ORDER_HISTORY_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )


def inquire_balance(token: str) -> dict:
    """국내주식 잔고를 조회한다."""
    tr_id = (
        kis_config.BALANCE_TR_ID_PAPER
        if kis_config.is_paper()
        else kis_config.BALANCE_TR_ID_REAL
    )

    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
    }

    return kis_client.get(
        endpoint=kis_config.BALANCE_ENDPOINT,
        tr_id=tr_id,
        token=token,
        params=params,
    )
