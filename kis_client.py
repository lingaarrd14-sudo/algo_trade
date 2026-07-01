import requests
import kis_config

# =========================================================
# 공통 HTTP 요청 처리
# =========================================================

def build_headers(token: str, tr_id: str) -> dict[str, str]:
    """한국투자증권 Open API 호출에 필요한 공통 헤더를 만든다."""
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": kis_config.APP_KEY,
        "appsecret": kis_config.APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    }


def issue_hashkey(body: dict) -> str:
    """주문 POST 요청 body로 hashkey를 발급받는다."""
    url = f"{kis_config.get_base_url()}{kis_config.HASHKEY_ENDPOINT}"
    headers = {
        "Content-Type": "application/json",
        "appkey": kis_config.APP_KEY,
        "appsecret": kis_config.APP_SECRET,
    }

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=10,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"HASHKEY 오류: {response.status_code} / {response.text}")

    data = response.json()
    hashkey = data.get("HASH") or data.get("hashkey")
    if not hashkey:
        raise RuntimeError(f"HASHKEY 응답에 hash 값이 없습니다: {data}")

    return hashkey


def get(endpoint: str, tr_id: str, token: str, params: dict) -> dict:
    """GET 방식 API를 호출하고 JSON 응답을 반환한다."""
    url = f"{kis_config.get_base_url()}{endpoint}"
    headers = build_headers(token, tr_id)

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"GET 오류: {response.status_code} / {response.text}")

    return response.json()


def post_order(endpoint: str, tr_id: str, token: str, body: dict) -> dict:
    """주문 POST API를 호출하고 JSON 응답을 반환한다."""
    url = f"{kis_config.get_base_url()}{endpoint}"
    headers = build_headers(token, tr_id)
    headers["hashkey"] = issue_hashkey(body)

    response = requests.post(
        url,
        headers=headers,
        json=body,
        timeout=10,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"POST 오류: {response.status_code} / {response.text}")

    return response.json()
