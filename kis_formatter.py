"""
파일명: kis_formatter.py
역할: 한국투자증권 Open API의 복잡한 응답 데이터(JSON)를 
      사람이 읽기 편한 깔끔한 텍스트 포맷으로 가공(파싱)하는 전용 모듈
"""

def _safe_int(val, default=0) -> int:
    """문자열 숫자를 안전하게 정수(int)로 변환합니다."""
    try:
        if not val:
            return default
        return int(float(str(val).replace(",", "").strip()))
    except (ValueError, TypeError):
        return default


def _safe_float(val, default=0.0) -> float:
    """문자열 숫자를 안전하게 실수(float)로 변환합니다."""
    try:
        if not val:
            return default
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def format_domestic_balance(data: dict) -> str:
    """
    국내주식 잔고 및 예수금 응답 데이터를 보기 좋은 텍스트로 가공합니다.
    """
    # 1. API 응답 에러 체크
    if not isinstance(data, dict) or data.get("rt_cd") != "0":
        msg = data.get("msg1", "알 수 없는 오류") if isinstance(data, dict) else "응답 데이터 없음"
        return f"❌ [국내 잔고 조회 실패] {msg}"

    # 2. 계좌 총 요약 정보 파싱 (output2)
    output2 = data.get("output2", [])
    summary = output2[0] if isinstance(output2, list) and len(output2) > 0 else {}

    tot_evlu_amt = _safe_int(summary.get("tot_evlu_amt"))  # 총 평가금액
    dnca_tot_amt = _safe_int(summary.get("dnca_tot_amt"))  # 예수금 (D+2)
    evlu_pfls_smttl_amt = _safe_int(summary.get("evlu_pfls_smttl_amt"))  # 총 평가손익
    
    # 수익률 부호 처리
    profit_symbol = "🔺 +" if evlu_pfls_smttl_amt > 0 else ("🔻 " if evlu_pfls_smttl_amt < 0 else "")

    lines = []
    lines.append("=" * 60)
    lines.append("💼 [국내주식] 계좌 잔고 현황")
    lines.append("-" * 60)
    lines.append(f"• 총 평가금액 : {tot_evlu_amt:,} 원")
    lines.append(f"• 예수금(D+2) : {dnca_tot_amt:,} 원")
    lines.append(f"• 총 평가손익 : {profit_symbol}{evlu_pfls_smttl_amt:,} 원")
    lines.append("-" * 60)
    lines.append(f"{'종목명':<12} {'보유수량':<8} {'평균단가':<10} {'현재가':<10} {'평가손익':<12} {'수익률'}")
    lines.append("-" * 60)

    # 3. 종목별 상세 현황 파싱 (output1)
    output1 = data.get("output1", [])
    if isinstance(output1, dict):
        output1 = [output1]

    has_stock = False
    for item in output1:
        qty = _safe_int(item.get("hldg_qty"))  # 보유 수량
        if qty <= 0:
            continue
        
        has_stock = True
        name = str(item.get("prdt_name", "미상")).strip()
        avg_price = _safe_int(item.get("pchs_avg_pric"))  # 매입 평균단가
        curr_price = _safe_int(item.get("prpr"))          # 현재가
        profit_amt = _safe_int(item.get("evlu_pfls_amt")) # 평가 손익
        profit_rate = _safe_float(item.get("evlu_pfls_rt")) # 수익률 (%)

        rate_symbol = "+" if profit_rate > 0 else ""
        rate_str = f"{rate_symbol}{profit_rate:.2f}%"

        lines.append(
            f"{name:<12} {qty:<8} {avg_price:<10,} {curr_price:<10,} {profit_amt:<12,} {rate_str}"
        )

    if not has_stock:
        lines.append(" (보유 중인 주식이 없습니다)")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_overseas_balance(data: dict) -> str:
    """
    해외주식 잔고 및 외화 평가 응답 데이터를 보기 좋은 텍스트로 가공합니다.
    """
    if not isinstance(data, dict) or data.get("rt_cd") != "0":
        msg = data.get("msg1", "알 수 없는 오류") if isinstance(data, dict) else "응답 데이터 없음"
        return f"❌ [해외 잔고 조회 실패] {msg}"

    output2 = data.get("output2", {})
    if isinstance(output2, list) and len(output2) > 0:
        output2 = output2[0]

    tot_evlu_amt = _safe_float(output2.get("tot_evlu_pfls_amt")) # 외화 총 평가손익 (달러)
    frcr_dncl = _safe_float(output2.get("frcr_dncl_amt_2"))      # 외화 예수금 (달러)

    lines = []
    lines.append("=" * 60)
    lines.append("💼 [해외주식] 계좌 잔고 현황 (USD)")
    lines.append("-" * 60)
    lines.append(f"• 외화 예수금 : $ {frcr_dncl:,.2f}")
    lines.append(f"• 외화 평가손익: $ {tot_evlu_amt:,.2f}")
    lines.append("-" * 60)
    lines.append(f"{'티커':<10} {'보유수량':<8} {'평균단가($)':<12} {'현재가($)':<12} {'수익률'}")
    lines.append("-" * 60)

    output1 = data.get("output1", [])
    if isinstance(output1, dict):
        output1 = [output1]

    has_stock = False
    for item in output1:
        qty = _safe_int(item.get("ovrs_ccls_qty", item.get("ccls_qty", 0)))
        if qty <= 0:
            continue
        
        has_stock = True
        ticker = str(item.get("ovrs_pdno", item.get("pdno", "미상"))).strip()
        avg_price = _safe_float(item.get("pchs_avg_pric"))
        curr_price = _safe_float(item.get("now_pric2", item.get("ovrs_prpr", 0)))
        profit_rate = _safe_float(item.get("evlu_pfls_rt"))

        rate_symbol = "+" if profit_rate > 0 else ""
        rate_str = f"{rate_symbol}{profit_rate:.2f}%"

        lines.append(
            f"{ticker:<10} {qty:<8} {avg_price:<12,.2f} {curr_price:<12,.2f} {rate_str}"
        )

    if not has_stock:
        lines.append(" (보유 중인 해외주식이 없습니다)")

    lines.append("=" * 60)
    return "\n".join(lines)


def format_domestic_price(data: dict, stock_code: str) -> str:
    """국내주식 현재가 시세 데이터를 보기 좋은 텍스트로 가공합니다."""
    if not isinstance(data, dict) or data.get("rt_cd") != "0":
        msg = data.get("msg1", "알 수 없는 오류") if isinstance(data, dict) else "응답 데이터 없음"
        return f"❌ [국내 시세 조회 실패] {msg}"

    output = data.get("output", {})
    stock_name = str(output.get("hts_kor_isnm") or output.get("prdt_name") or output.get("rprc_isnm") or "").strip()
    curr_price = _safe_int(output.get("stck_prpr")) # 현재가
    diff_price = _safe_int(output.get("prdy_vrss")) # 전일 대비 금액
    diff_rate = _safe_float(output.get("prdy_ctrt")) # 전일 대비 등락률 (%)
    volume = _safe_int(output.get("acml_vol"))       # 누적 거래량

    symbol = "🔺 +" if diff_price > 0 else ("🔻 " if diff_price < 0 else "")

    lines = []
    lines.append("=" * 50)
    if stock_name:
        lines.append(f"🔍 [국내 시세] {stock_name} ({stock_code})")
    else:
        lines.append(f"🔍 [국내 시세] 종목코드: {stock_code}")
    lines.append("-" * 50)
    if stock_name:
        lines.append(f"• 종목명   : {stock_name}")
    lines.append(f"• 현재가   : {curr_price:,} 원")
    lines.append(f"• 전일대비 : {symbol}{diff_price:,} 원 ({diff_rate:+.2f}%)")
    lines.append(f"• 거래량   : {volume:,} 주")
    lines.append("=" * 50)
    return "\n".join(lines)



def format_overseas_price(data: dict, ticker: str) -> str:
    """해외주식 현재가 시세 데이터를 보기 좋은 텍스트로 가공합니다."""
    if not isinstance(data, dict) or data.get("rt_cd") != "0":
        msg = data.get("msg1", "알 수 없는 오류") if isinstance(data, dict) else "응답 데이터 없음"
        return f"❌ [해외 시세 조회 실패] {msg}"

    output = data.get("output", {})
    curr_price = _safe_float(output.get("last")) # 현재가 (최종가)
    diff_price = _safe_float(output.get("diff")) # 등락금액
    diff_rate = _safe_float(output.get("rate")) # 등락률 (%)

    symbol = "🔺 +" if diff_price > 0 else ("🔻 " if diff_price < 0 else "")

    lines = []
    lines.append("=" * 50)
    lines.append(f"🔍 [해외 시세] 티커: {ticker.upper()}")
    lines.append("-" * 50)
    lines.append(f"• 현재가   : $ {curr_price:,.2f}")
    lines.append(f"• 전일대비 : {symbol}$ {diff_price:,.2f} ({diff_rate:+.2f}%)")
    lines.append("=" * 50)
    return "\n".join(lines)


def format_order_history(data: dict, title: str = "당일 주문/체결 내역") -> str:
    """오늘 발생한 주문 및 체결 내역 데이터를 보기 좋은 텍스트로 가공합니다."""
    if not isinstance(data, dict) or data.get("rt_cd") != "0":
        msg = data.get("msg1", "알 수 없는 오류") if isinstance(data, dict) else "응답 데이터 없음"
        return f"❌ [{title} 조회 실패] {msg}"

    output1 = data.get("output1", [])
    if isinstance(output1, dict):
        output1 = [output1]

    lines = []
    lines.append("=" * 70)
    lines.append(f"📜 [{title}]")
    lines.append("-" * 70)
    lines.append(f"{'주문번호':<10} {'종목/티커':<10} {'구분':<6} {'주문수량':<8} {'체결수량':<8} {'상태'}")
    lines.append("-" * 70)

    has_history = False
    for item in output1:
        order_no = str(item.get("odno", "")).strip()
        if not order_no:
            continue
        
        has_history = True
        code = str(item.get("pdno", "미상")).strip()
        
        # 매수/매도 구분
        side_code = str(item.get("sll_buy_dvsn_cd", item.get("sll_buy_dvsn", ""))).strip()
        side_name = "매수" if side_code in ("02", "BUY") else ("매도" if side_code in ("01", "SELL") else "기타")
        
        ord_qty = _safe_int(item.get("ord_qty", item.get("ft_ord_qty", 0)))
        ccld_qty = _safe_int(item.get("tot_ccld_qty", item.get("ft_ccld_qty", item.get("ccld_qty", 0))))
        unfilled_qty = _safe_int(item.get("nccs_qty", 0))

        status = "✅ 체결완료" if unfilled_qty == 0 and ccld_qty > 0 else f"⏳ 미체결({unfilled_qty}주)"

        lines.append(
            f"{order_no:<10} {code:<10} {side_name:<6} {ord_qty:<8} {ccld_qty:<8} {status}"
        )

    if not has_history:
        lines.append(" (당일 발생한 주문 내역이 없습니다)")

    lines.append("=" * 70)
    return "\n".join(lines)
