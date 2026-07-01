<<<<<<< HEAD
# KIS Domestic Stock API 예제

한국투자증권(KIS) Open API를 사용해서 국내주식 현재가, 주문/체결, 미체결, 잔고를 조회하는 Python 예제 프로젝트입니다.

## 파일 구성

- `kis_config.py`: `.env` 설정값, API 서버 주소, Endpoint, TR_ID를 관리합니다.
- `kis_auth.py`: Access Token을 발급하고 로컬 캐시에 저장합니다.
- `kis_client.py`: 공통 HTTP 헤더 생성과 GET/POST 요청을 담당합니다.
- `kis_domestic_stock.py`: 국내주식 현재가, 주문, 주문 내역, 미체결, 잔고 API를 제공합니다.
- `main.py`: 주요 기능을 순서대로 실행하는 샘플 코드입니다.

## 설치

```bash
pip install requests python-dotenv
```

## 환경 변수

프로젝트 루트에 `.env` 파일을 만들고 아래 값을 입력합니다.

```env
KIS_ENV=paper
KIS_APP_KEY=발급받은_APP_KEY
KIS_APP_SECRET=발급받은_APP_SECRET
KIS_ACCOUNT_NO=계좌번호_앞8자리
KIS_ACCOUNT_PRODUCT_CODE=01
```

`KIS_ENV`는 모의투자면 `paper`, 실전투자면 `real`로 설정합니다.

## 실행

```bash
python main.py
```

기본 예제는 삼성전자(`005930`)를 대상으로 현재가, 주문/체결, 미체결, 잔고를 조회합니다.

## 주문 테스트

`main.py`의 매수 주문 예제는 기본적으로 주석 처리되어 있습니다. 실제 주문을 테스트할 때만 주석을 해제하고 수량과 가격을 확인하세요.

```python
# buy_result = order_stock(
#     token=token,
#     order_type="buy",
#     stock_code=stock_code,
#     quantity=1,
#     price=70000,
# )
```

## 토큰 캐시

Access Token은 `.kis_token_cache.json`에 저장됩니다. 환경이 바뀌거나 토큰이 만료되면 자동으로 새 토큰을 발급합니다.

## 주의사항

- 실전투자(`KIS_ENV=real`)에서는 실제 주문이 접수될 수 있습니다.
- `.env`와 `.kis_token_cache.json`은 외부에 공유하지 마세요.
- 한국투자증권 Open API의 계좌 권한, 앱 승인 상태, 모의투자/실전투자 환경을 먼저 확인하세요.
=======
# algo_trade
This is python algorithm trading code and environment.
>>>>>>> 3b074537335087245e5938552d6053d40cdbd271
