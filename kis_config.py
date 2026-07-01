from pathlib import Path
import os
from dotenv import load_dotenv

<<<<<<< HEAD
=======

>>>>>>> 3b074537335087245e5938552d6053d40cdbd271
# =========================================================
# 환경 변수(.env) 로드
# =========================================================

<<<<<<< HEAD
BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

# =========================================================
# 실행 환경 및 인증 정보
# =========================================================

KIS_ENV = os.getenv("KIS_ENV", "paper")

APP_KEY = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO")
ACCOUNT_PRODUCT_CODE = os.getenv("KIS_ACCOUNT_PRODUCT_CODE", "01")

# =========================================================
# Access Token 캐시
# =========================================================

CACHE_FILE = BASE_DIR / ".kis_token_cache.json"

=======
# 현재 파일(kis_config.py)이 위치한 폴더 경로
BASE_DIR = Path(__file__).parent

# .env 파일 로드
load_dotenv(BASE_DIR / ".env")


# =========================================================
# 실행 환경 설정
# =========================================================

# 실행 환경
# - "paper" : 모의투자
# - "real"  : 실전투자
# 기본값은 paper
KIS_ENV = os.getenv("KIS_ENV", "paper")


# =========================================================
# OpenAPI 인증 정보
# =========================================================

# 한국투자 OpenAPI App Key
# 국내/해외 공통 사용
APP_KEY = os.getenv("KIS_APP_KEY")

# 한국투자 OpenAPI App Secret
# 국내/해외 공통 사용
APP_SECRET = os.getenv("KIS_APP_SECRET")


# =========================================================
# 계좌 정보
# =========================================================

# 계좌번호 앞 8자리
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO")

# 계좌 상품코드
# 일반적으로 "01"
ACCOUNT_PRODUCT_CODE = os.getenv("KIS_ACCOUNT_PRODUCT_CODE")


# =========================================================
# Access Token 캐시 파일
# =========================================================

# 발급받은 access token 저장 파일
CACHE_FILE = BASE_DIR / ".kis_token_cache.json"


>>>>>>> 3b074537335087245e5938552d6053d40cdbd271
# =========================================================
# 서버 주소
# =========================================================

<<<<<<< HEAD
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"

# =========================================================
# API Endpoint / TR_ID
# =========================================================

TOKEN_ENDPOINT = "/oauth2/tokenP"
HASHKEY_ENDPOINT = "/uapi/hashkey"

PRICE_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-price"
PRICE_TR_ID = "FHKST01010100"

ORDER_ENDPOINT = "/uapi/domestic-stock/v1/trading/order-cash"
BUY_TR_ID_REAL = "TTTC0012U"
SELL_TR_ID_REAL = "TTTC0011U"
BUY_TR_ID_PAPER = "VTTC0012U"
SELL_TR_ID_PAPER = "VTTC0011U"

ORDER_HISTORY_ENDPOINT = "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
ORDER_HISTORY_TR_ID_REAL = "TTTC0081R"
ORDER_HISTORY_TR_ID_PAPER = "VTTC0081R"

BALANCE_ENDPOINT = "/uapi/domestic-stock/v1/trading/inquire-balance"
BALANCE_TR_ID_REAL = "TTTC8434R"
BALANCE_TR_ID_PAPER = "VTTC8434R"


def is_paper() -> bool:
    """현재 환경이 모의투자인지 확인한다."""
    return KIS_ENV != "real"


def get_base_url() -> str:
    """실행 환경에 맞는 한국투자증권 Open API 서버 주소를 반환한다."""
    return PAPER_BASE_URL if is_paper() else REAL_BASE_URL
=======
# 실전투자 서버
# 국내/해외 공통
REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"

# 모의투자 서버
# 국내/해외 공통
PAPER_BASE_URL = "https://openapivts.koreainvestment.com:29443"


# =========================================================
# OAuth 인증 API
# =========================================================

# Access Token 발급 API
TOKEN_ENDPOINT = "/oauth2/tokenP"


# =========================================================
# 국내주식 시세 API
# =========================================================

# 국내주식 현재가 조회 Endpoint
PRICE_ENDPOINT = "/uapi/domestic-stock/v1/quotations/inquire-price"

# 국내주식 현재가 조회 TR_ID
# FHKST = 국내주식 시세 계열
PRICE_TR_ID = "FHKST01010100"


# =========================================================
# 국내주식 주문 API
# =========================================================

# 국내주식 현금 주문 Endpoint
ORDER_ENDPOINT = "/uapi/domestic-stock/v1/trading/order-cash"

# 국내주식 모의투자 매수 주문 TR_ID
# VTTC = Virtual Trading Test Center
PAPER_BUY_TR_ID = "VTTC0012U"

# 국내주식 모의투자 매도 주문 TR_ID
PAPER_SELL_TR_ID = "VTTC0011U"


# =========================================================
# 국내주식 주문/체결 조회 API
# =========================================================

# 주문내역 조회 Endpoint
ORDER_HISTORY_ENDPOINT = (
    "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
)

# 실전 주문내역 조회 TR_ID
ORDER_HISTORY_TR_ID_REAL = "TTTC0081R"

# 모의 주문내역 조회 TR_ID
ORDER_HISTORY_TR_ID_DEMO = "VTTC0081R"


# =========================================================
# 국내주식 미체결 조회 API
# =========================================================

# 미체결 조회 Endpoint
UNFILLED_ENDPOINT = (
    "/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
)

# 실전 미체결 조회 TR_ID
UNFILLED_TR_ID_REAL = "TTTC0081R"

# 모의 미체결 조회 TR_ID
UNFILLED_TR_ID_DEMO = "VTTC0081R"


# =========================================================
# 국내주식 잔고 조회 API
# =========================================================

# 잔고 조회 Endpoint
BALANCE_ENDPOINT = (
    "/uapi/domestic-stock/v1/trading/inquire-balance"
)

# 실전 잔고 조회 TR_ID
BALANCE_TR_ID_REAL = "TTTC8434R"

# 모의 잔고 조회 TR_ID
BALANCE_TR_ID_DEMO = "VTTC8434R"


# =========================================================
# 환경별 Base URL 반환
# =========================================================

def get_base_url(env_name: str) -> str:
    
    if env_name == "real":
        return REAL_BASE_URL

    return PAPER_BASE_URL
>>>>>>> 3b074537335087245e5938552d6053d40cdbd271
