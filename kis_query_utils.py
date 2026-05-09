import time
import json
import os
import requests
from datetime import datetime

import kis_config
from kis_config import get_base_url

#토큰 캐시 읽기 함수
def _read_cached_token() -> str | None:
    if not kis_config.CACHE_FILE.exists():
        return None

    try:
        data = json.loads(kis_config.CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    token = data.get("access_token")
    expires_at = data.get("expires_at")
    env_name = data.get("env_name")

    # 캐시된 토큰이 유효한지 확인, 시간 부족하면 새로 발급하도록 None 반환
    if not token or not expires_at:
        return None
    if env_name != os.getenv("KIS_ENV", "demo"):
        return None
    if time.time() >= float(expires_at) - 60:
        return None
    return token

#토큰 캐시 쓰기 함수
def _write_cached_token(env_name: str, token: str, expires_in: int) -> None:
    payload = {
        "env_name": env_name,
        "access_token": token,
        "expires_at": time.time() + expires_in,
    }
    kis_config.CACHE_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

#토큰 발급 함수
def issue_access_token() -> str:
    cached = _read_cached_token()
    if cached:
        return cached

    url = f"{get_base_url(kis_config.KIS_ENV)}{kis_config.TOKEN_ENDPOINT}" # 실제 요청 주소 만들기 url+endpoint
    headers = {"Content-Type": "application/json"}                         #요청 헤더 설정 #KIS API는 JSON 형식의 요청을 기대하므로 Content-Type을 application/json 설정
    body = {                                                               #요청 본문 설정
        "grant_type": "client_credentials",
        "appkey": kis_config.APP_KEY,
        "appsecret": kis_config.APP_SECRET,
    }

    if not kis_config.APP_KEY or not kis_config.APP_SECRET:
        print()
        print("KIS_APP_KEY 또는 KIS_APP_SECRET이 없습니다.")
    else:
        print()
        print("토큰 요청 본문(JSON)")
        print(json.dumps(body, ensure_ascii=False, indent=2))  

        response = requests.post(url, headers=headers, json=body, timeout=10) # 토큰 요청 보내기

        response.raise_for_status() #응답이 성공적이지 않으면 예외 발생
        data = response.json() #응답을 JSON으로 파싱

        print("########################################")
        print("토큰 발급 성공")

        expires_in = int(data.get("expires_in") or 3600)
        _write_cached_token(kis_config.KIS_ENV, data["access_token"], expires_in)

        print(f"access_token 일부: {data['access_token'][:10]}...")
        return data["access_token"] #발급된 토큰 반환

#헤더 빌드 함수
def build_headers(token, tr_id):
    return {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": kis_config.APP_KEY,
        "appsecret": kis_config.APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
}

#오늘 날짜 yyyymmdd 반환 함수
def today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")