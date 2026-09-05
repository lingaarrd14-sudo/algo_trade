import requests

from . import kis_config

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


def get_page(
    endpoint: str,
    tr_id: str,
    token: str,
    params: dict,
    tr_cont: str = "",
) -> tuple[dict, str]:
    """GET 응답과 KIS 연속조회 헤더를 함께 반환한다."""
    url = f"{kis_config.get_base_url()}{endpoint}"
    headers = build_headers(token, tr_id)
    if tr_cont:
        headers["tr_cont"] = tr_cont

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"GET 오류: {response.status_code} / {response.text}")

    return response.json(), response.headers.get("tr_cont", "")


def get(endpoint: str, tr_id: str, token: str, params: dict) -> dict:
    """기존 단일 페이지 호출 형식을 유지한다."""
    return get_page(endpoint, tr_id, token, params)[0]


def get_all_pages(
    endpoint: str,
    tr_id: str,
    token: str,
    params: dict,
    context_size: int,
    output_keys: tuple[str, ...],
    max_pages: int = 10,
) -> dict:
    """KIS FK/NK 연속키를 따라가며 지정된 출력 목록을 합친다."""
    params = dict(params)
    fk_name = f"CTX_AREA_FK{context_size}"
    nk_name = f"CTX_AREA_NK{context_size}"
    fk = nk = tr_cont = ""
    collected = {key: [] for key in output_keys}
    combined: dict = {}
    seen_contexts: set[tuple[str, str]] = set()

    for _ in range(max_pages):
        params[fk_name] = fk
        params[nk_name] = nk
        page, next_cont = get_page(endpoint, tr_id, token, params, tr_cont)
        if str(page.get("rt_cd", "")) != "0":
            return page
        if not combined:
            combined = dict(page)

        for key in output_keys:
            value = page.get(key, [])
            collected[key].extend(value if isinstance(value, list) else [value] if value else [])

        if next_cont not in {"M", "F"}:
            break

        # 응답 body의 소문자 연속키를 다음 요청에 그대로 전달한다.
        next_fk = str(page.get(f"ctx_area_fk{context_size}", "")).strip()
        next_nk = str(page.get(f"ctx_area_nk{context_size}", "")).strip()
        context = (next_fk, next_nk)
        if not any(context) or context in seen_contexts:
            raise RuntimeError("KIS 연속조회 키가 없거나 반복됩니다.")
        seen_contexts.add(context)
        fk, nk, tr_cont = next_fk, next_nk, "N"
    else:
        raise RuntimeError(f"KIS 연속조회가 {max_pages}페이지를 초과했습니다.")

    for key, rows in collected.items():
        combined[key] = rows
    return combined


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
