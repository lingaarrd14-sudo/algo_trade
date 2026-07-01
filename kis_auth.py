import json
import time
import requests
import kis_config

# =========================================================
# Access Token 캐시 관리
# =========================================================

def _read_cached_token() -> str | None:
    """유효한 토큰 캐시가 있으면 반환한다."""
    if not kis_config.CACHE_FILE.exists():
        return None

    try:
        data = json.loads(kis_config.CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    token = data.get("access_token")
    expires_at = data.get("expires_at")
    env_name = data.get("env_name")

    if not token or not expires_at:
        return None

    if env_name != kis_config.KIS_ENV:
        return None

    if time.time() >= float(expires_at) - 60:
        return None

    return token

# =========================================================
# Access Token 캐시 저장
# =========================================================

def _write_cached_token(token: str, expires_in: int) -> None:
    """새로 발급받은 토큰을 로컬 캐시에 저장한다."""
    payload = {
        "env_name": kis_config.KIS_ENV,
        "access_token": token,
        "expires_at": time.time() + expires_in,
    }

    kis_config.CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

# =========================================================
# Access Token 발급
# =========================================================

def issue_access_token() -> str:
    """
    캐시된 토큰을 우선 사용하고,
    없거나 만료되었으면 새로 발급한다.
    """
    # 캐시에 유효한 토큰이 있으면 재사용
    cached = _read_cached_token()
    if cached:
        return cached

    # 인증 정보가 없으면 실행 중단
    if not kis_config.APP_KEY or not kis_config.APP_SECRET:
        raise RuntimeError(".env 파일에 KIS_APP_KEY 또는 KIS_APP_SECRET이 없습니다.")

    url = f"{kis_config.get_base_url()}{kis_config.TOKEN_ENDPOINT}"

    body = {
        "grant_type": "client_credentials",
        "appkey": kis_config.APP_KEY,
        "appsecret": kis_config.APP_SECRET,
    }

    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        json=body,
        timeout=10,
    )

    if response.status_code >= 400:
        raise RuntimeError(f"토큰 발급 실패: {response.status_code} / {response.text}")

    data = response.json()
    token = data["access_token"]
    expires_in = int(data.get("expires_in") or 86400)

    # 새 토큰을 캐시에 저장
    _write_cached_token(token, expires_in)

    return token
