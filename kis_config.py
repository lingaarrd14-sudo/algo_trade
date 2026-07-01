from pathlib import Path
import os
from dotenv import load_dotenv

# =========================================================
# 환경 변수(.env) 로드
# =========================================================

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

# =========================================================
# 서버 주소
# =========================================================

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
