import json
import requests

from kis_query_utils import issue_access_token, build_headers, today_yyyymmdd
import kis_config


# 국내주식 현재가를 조회하고 주요 응답값을 콘솔에 보여준다.
def price_viewer(token: str, stock_code: str) -> None:

    url = f"{kis_config.get_base_url(kis_config.KIS_ENV)}{kis_config.PRICE_ENDPOINT}"

    headers = build_headers(token, kis_config.PRICE_TR_ID)  # t1101은 주식 현재가 조회 TR ID 예시입니다. 실제로는 필요한 TR ID로 변경해야 합니다.
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": stock_code,
    }

    response = requests.get(url, headers=headers, params=params, timeout=10)

    response.raise_for_status()
    data = response.json()

    print(f"기본 종목코드: {stock_code}")
    print()
    print(f"응답 코드: {data.get('rt_cd')}")
    print(f"메시지: {data.get('msg1')}")

    if data.get("rt_cd") == "0":
        output = data.get("output", {})
        stock_name = output.get("hts_kor_isnm") or output.get("prdt_name")
        if stock_name:
            print(f"종목명: {stock_name}")
        print(f"종목코드: {output.get('stck_shrn_iscd', stock_code)}")
        print(f"현재가: {output.get('stck_prpr', '확인 필요')}원")

    
def order_stock(
    token: str,
    order_type: str,
    stock_code: str,
    quantity: int,
    price: int,
) -> None:
    # 매수/매도 주문을 KIS 주문 API로 전송한다.

    print(token[:20])

    print("국내주식 모의주문 요청")

    # 주문 타입에 따라 TR_ID 선택
    if order_type == "buy":
        tr_id = kis_config.PAPER_BUY_TR_ID

    elif order_type == "sell":
        tr_id = kis_config.PAPER_SELL_TR_ID

    else:
        raise ValueError("order_type must be buy or sell")

    # 주문 데이터
    # KIS 주문 API가 요구하는 필드명에 맞춰 주문 본문을 구성한다.
    order_request_data = {
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

    print()
    print("[주문 전 확인]")
    print(json.dumps(order_request_data, ensure_ascii=False, indent=2))

    # API 요청
    url = (
        f"{kis_config.get_base_url(kis_config.KIS_ENV)}"
        f"{kis_config.ORDER_ENDPOINT}"
    )

    headers = build_headers(token, tr_id)

    # 주문 요청은 계좌에 영향을 줄 수 있으므로 응답 원문도 함께 확인한다.
    response = requests.post(
        url,
        headers=headers,
        json=order_request_data,
        timeout=10,
    )

    print(response.status_code)
    print(response.text)

    response.raise_for_status()

    result = response.json()

    print()
    print("주문 응답")

    print(json.dumps(result, ensure_ascii=False, indent=2))

    print(f"응답 코드: {result.get('rt_cd')}")
    print(f"메시지: {result.get('msg1')}")

# 오늘 날짜 기준으로 주문/체결 내역을 조회한다.
def order_history_check(token: str) -> None:

    print("국내주식 주문 조회")
    today = today_yyyymmdd()
    print(f"조회일자: {today}")

    print()

    # 실전/모의 환경에 맞는 조회 TR ID를 선택한다.
    tr_id = kis_config.ORDER_HISTORY_TR_ID_REAL if kis_config.KIS_ENV == "real" else kis_config.ORDER_HISTORY_TR_ID_DEMO
    headers = build_headers(token, tr_id)
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
    url = (
        f"{kis_config.get_base_url(kis_config.KIS_ENV)}"
        f"{kis_config.ORDER_HISTORY_ENDPOINT}"
    )
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    print()
    print("주문 조회 응답")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"응답 코드: {data.get('rt_cd')}")
    print(f"메시지: {data.get('msg1')}")

    orders = data.get("output1", [])
    print(f"주문 건수: {len(orders)}")
    if orders:
        print()
        print("[최근 주문 요약]")
        for order in orders:
            print(
                f"- 주문번호 {order.get('odno')} / {order.get('prdt_name')} / "
                f"{order.get('sll_buy_dvsn_cd_name')} / "
                f"주문수량 {order.get('ord_qty')} / "
                f"주문가격 {order.get('ord_unpr')} / "
                f"체결수량 {order.get('tot_ccld_qty')} / "
                f"미체결수량 {order.get('rmn_qty')}"
            )

# 오늘 발생한 주문 중 아직 체결되지 않은 주문만 조회한다.
def unfilled_orders_check(token : str) -> None:

    print("국내주식 미체결 조회")
    today = today_yyyymmdd()
    print(f"조회일자: {today}")
    print()

    print("2) 오늘 미체결 조회")

    tr_id = kis_config.UNFILLED_TR_ID_REAL if kis_config.KIS_ENV == "real" else kis_config.UNFILLED_TR_ID_DEMO
    headers = build_headers(token, tr_id)
    params = {
        "CANO": kis_config.ACCOUNT_NO,
        "ACNT_PRDT_CD": kis_config.ACCOUNT_PRODUCT_CODE,
        "INQR_STRT_DT": today,
        "INQR_END_DT": today,
        "SLL_BUY_DVSN_CD": "00",
        "INQR_DVSN": "00",
        "PDNO": "",
        # 02는 미체결 주문만 조회하도록 하는 구분값이다.
        "CCLD_DVSN": "02",
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
        "EXCG_ID_DVSN_CD": "KRX",
    }

    url = (
    f"{kis_config.get_base_url(kis_config.KIS_ENV)}"
    f"{kis_config.UNFILLED_ENDPOINT}"
    )
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    

    print()
    print("미체결 조회 응답")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"응답 코드: {data.get('rt_cd')}")
    print(f"메시지: {data.get('msg1')}")

    orders = data.get("output1", [])
    print(f"미체결 건수: {len(orders)}")
    if orders:
        print()
        print("[미체결 주문 요약]")
        for order in orders:
            print(
                f"- 주문번호 {order.get('odno')} / {order.get('prdt_name')} / "
                f"{order.get('sll_buy_dvsn_cd_name')} / "
                f"주문수량 {order.get('ord_qty')} / "
                f"체결수량 {order.get('tot_ccld_qty')} / "
                f"미체결수량 {order.get('rmn_qty')} / "
                f"주문가격 {order.get('ord_unpr')}"
            )

# 현재 보유 종목과 계좌 평가 요약을 조회한다.
def balance_check(token: str) -> None:
    print("국내주식 잔고 조회")

    print(" 현재 잔고 조회")
    tr_id = kis_config.BALANCE_TR_ID_REAL if kis_config.KIS_ENV == "real" else kis_config.BALANCE_TR_ID_DEMO
    headers = build_headers(token, tr_id)
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

    url = (
    f"{kis_config.get_base_url(kis_config.KIS_ENV)}"
    f"{kis_config.BALANCE_ENDPOINT}"
    )
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    print()
    print("잔고 조회 응답")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"응답 코드: {data.get('rt_cd')}")
    print(f"메시지: {data.get('msg1')}")

    positions = data.get("output1", [])
    summary = data.get("output2", [])
    print(f"보유 종목 수: {len(positions)}")
    if positions:
        print()
        print("[보유 종목 요약]")
        for stock in positions:
            print(
                f"- {stock.get('prdt_name')} / "
                f"보유수량 {stock.get('hldg_qty')} / "
                f"평균매입가 {stock.get('pchs_avg_pric')} / "
                f"현재가 {stock.get('prpr')} / "
                f"평가손익률 {stock.get('evlu_pfls_rt')}"
            )

    if isinstance(summary, list) and summary:
        row = summary[0]
        print()
        print("[잔고 요약]")
        print(f"예수금 총액: {row.get('dnca_tot_amt')}")
        print(f"유가평가금액: {row.get('scts_evlu_amt')}")
        print(f"총평가금액: {row.get('tot_evlu_amt')}")
        print(f"평가손익합계금액: {row.get('evlu_pfls_smtl_amt')}")
