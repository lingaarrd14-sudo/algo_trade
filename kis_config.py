"""
파일명: kis_config.py
역할: 한국투자증권 Open API 연동을 위한 환경 변수 로드 및 국내/해외 설정 상수(Constants) 관리 파일
"""

from pathlib import Path
import os
from dotenv import load_dotenv

# =========================================================
# 1. 환경 변수(.env) 로드 및 기본 디렉토리 설정
# =========================================================
BASE_DIR = Path(__file__).parent
# override=True를 주어 시스템 환경변수보다 .env 파일의 설정을 우선하도록 합니다.
load_dotenv(BASE_DIR / ".env", override=True)

# =========================================================
# 2. 실행 환경 및 계좌 인증 정보 관리
# =========================================================
# KIS_ENV가 'real'이면 실전투자, 없거나 다르면 'paper'(모의투자)로 인식합니다.
KIS_ENV = os.getenv("KIS_ENV", "paper")

APP_KEY = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO")                # 계좌번호 앞 8자리
ACCOUNT_PRODUCT_CODE = os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01") # 계좌 상품코드 (보통 01)

# 발급받은 Access Token을 매번 요청하지 않고 로컬에 임시 저장할 캐시 파일 주소
CACHE_FILE = BASE_DIR / ".kis_token_cache.json"

# =========================================================
# 3. 한국투자증권 API 서버 주소 (실전 vs 모의)
# =========================================================
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"  # 실전투자 서버
PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443" # 모의투자 서버

# =========================================================
# 4. 공통 API 엔드포인트 (국내/해외 주식 공통 사용)
# =========================================================
TOKEN_ENDPOINT = "/oauth2/tokenP"  # 접근 토큰 발급 주소
HASHKEY_ENDPOINT = "/uapi/hashkey" # 주문 데이터 변조 방지용 해시 생성 주소

# =========================================================
# 5. 국내주식(DOMESTIC) API 설정 상수
# =========================================================
# [국내] 현재가 조회
DOMESTIC_PRICE_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-price"
DOMESTIC_PRICE_TR_ID = "FHKST01010100"

# [국내] 주식 현금 주문 (매수/매도 공통 엔드포인트)
DOMESTIC_ORDER_ENDPOINT = "/uapi/domestic-stock/v1/trading/order-cash"
DOMESTIC_BUY_TR_ID_REAL = "TTTC0012U"   # 실전 매수
DOMESTIC_SELL_TR_ID_REAL = "TTTC0011U"  # 실전 매도
DOMESTIC_BUY_TR_ID_PAPER = "VTTC0012U"  # 모의 매수
DOMESTIC_SELL_TR_ID_PAPER = "VTTC0011U" # 모의 매도

# [국내] 주문/체결 및 미체결 조회
DOMESTIC_ORDER_HISTORY_ENDPOINT = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
DOMESTIC_ORDER_HISTORY_TR_ID_REAL = "TTTC0081R"  # 실전 조회
DOMESTIC_ORDER_HISTORY_TR_ID_PAPER = "VTTC0081R" # 모의 조회

# [국내] 잔고 조회
DOMESTIC_BALANCE_ENDPOINT = "/uapi/domestic-stock/v1/trading/inquire-balance"
DOMESTIC_BALANCE_TR_ID_REAL = "TTTC8434R"  # 실전 잔고
DOMESTIC_BALANCE_TR_ID_PAPER = "VTTC8434R" # 모의 잔고

# =========================================================
# 6. 해외주식(OVERSEAS) API 설정 상수
# =========================================================
# [해외] 현재가 조회 (상세지연 및 실시간 시세) (26.07.05 수정): 공식api문서 TR ID로 교체
OVERSEAS_PRICE_ENDPOINT = "/uapi/overseas-price/v1/quotations/price"
OVERSEAS_PRICE_TR_ID = "HHDFS00000300"

# [해외] 주식 주문 (26.07.05 수정): 공식api문서 TR ID로 교체
OVERSEAS_ORDER_ENDPOINT = "/uapi/overseas-stock/v1/trading/order"
OVERSEAS_BUY_TR_ID_REAL = "TTTT1002U"   
OVERSEAS_SELL_TR_ID_REAL = "TTTT1001U"  
OVERSEAS_BUY_TR_ID_PAPER = "VTTT1002U"  
OVERSEAS_SELL_TR_ID_PAPER = "VTTT1001U" 

# [해외] 주문/체결 조회 (끝부분을 ccnl 로 수정) (26.07.05 수정): 공식api문서 TR ID로 교체
OVERSEAS_ORDER_HISTORY_ENDPOINT = "/uapi/overseas-stock/v1/trading/inquire-ccnl"
OVERSEAS_ORDER_HISTORY_TR_ID_REAL = "TTTS3035R"
OVERSEAS_ORDER_HISTORY_TR_ID_PAPER = "VTTS3035R"

# [해외] 잔고 조회 (26.07.05 수정): 공식api문서 TR ID로 교체
OVERSEAS_BALANCE_ENDPOINT = "/uapi/overseas-stock/v1/trading/inquire-balance"
OVERSEAS_BALANCE_TR_ID_REAL = "TTTS3012R"
OVERSEAS_BALANCE_TR_ID_PAPER = "VTTS3012R"

# =========================================================
# 7. 실행 환경 판단용 헬퍼 함수
# =========================================================
def is_paper() -> bool:
    """현재 실행 환경이 모의투자 환경인지 확인합니다."""
    return KIS_ENV != "real"


def get_base_url() -> str:
    """현재 설정 환경(실전/모의)에 맞는 메인 도메인 주소를 반환합니다."""
    return PAPER_BASE_URL if is_paper() else REAL_BASE_URL