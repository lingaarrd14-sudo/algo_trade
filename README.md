# algotrade

한국투자증권 OPEN API를 활용한 알고리즘 트레이딩 구현 프로젝트입니다. 포트폴리오 효과 구현 등 다양한 전략 개발을 목표로 하고 있습니다.

> 주의: 실제 계좌와 연결하면 실제 주문이 나갈 수 있습니다. 처음에는 반드시 모의투자(`KIS_ENV=paper`)로 테스트하세요.

## 기능

- KIS Open API access token 발급 및 로컬 캐시
- 국내 주식 현재가 조회
- 국내 주식 시장가 매수/매도
- 국내 주식 주문/체결 내역 조회
- 국내 주식 잔고 조회
- 해외 주식 현재가 조회
- 해외 주식 시장가 매수/매도
- 해외 주식 주문/체결 내역 조회
- 해외 주식 잔고 조회
- 미체결 주문 처리
- 콘솔 메뉴 방식 조회 프로그램
- 시간 기반 자동매매 스케줄러

## 폴더 구조

```text
algotrade/
├─ kis/
│  ├─ kis_config.py          # 환경변수, API URL, endpoint, TR ID 설정
│  ├─ kis_auth.py            # access token 발급 및 캐시
│  ├─ kis_client.py          # 공통 GET/POST 요청 처리
│  ├─ kis_domestic_stock.py  # 국내 주식 조회/주문/잔고
│  └─ kis_overseas_stock.py  # 해외 주식 조회/주문/잔고
├─ interface/
│  ├─ cli.py                 # 콘솔 메뉴 프로그램
│  └─ kis_formatter.py       # API 응답 출력 포맷
├─ strategy/
│  └─ test.py                # 시간 기반 자동매매 실행 파일
├─ requirements.txt
└─ README.md
```

## 설치

```powershell
pip install -r requirements.txt
```

## 환경변수 설정

`kis/.env` 파일을 만들고 아래 값을 넣습니다.

```env
KIS_ENV=paper
KIS_APP_KEY=발급받은_APP_KEY
KIS_APP_SECRET=발급받은_APP_SECRET
KIS_ACCOUNT_NO=계좌번호_앞_8자리
KIS_ACCOUNT_PRODUCT_CODE=01
```

`KIS_ENV` 값:

- `paper`: 모의투자
- `real`: 실전투자

토큰 캐시는 `kis/.kis_token_cache.json`에 저장됩니다. 환경을 바꾸거나 인증 문제가 생기면 이 파일을 삭제한 뒤 다시 실행하면 됩니다.

## 실행

프로젝트 루트(`C:\python\algotrade`)에서 실행하세요.

### 콘솔 메뉴 실행

잔고, 현재가, 주문 내역을 메뉴로 조회합니다.

```powershell
python interface\cli.py
```

### 자동매매 스케줄러 실행

`strategy/test.py`에 설정된 시간에 삼성전자와 애플을 시장가로 매수/매도합니다.

```powershell
python strategy\test.py
```

현재 기본 설정:

- 국내 주식: 삼성전자(`005930`) 1주
- 해외 주식: 애플(`AAPL`) 1주
- 국내 매수: `09:05`
- 국내 매도: `15:20`
- 해외 매수: `22:35`
- 해외 매도: `04:55`

종목, 수량, 시간은 `strategy/test.py`의 `main()` 함수 안에서 바꿀 수 있습니다.

## 사용 전 확인사항

- 한국투자증권 Open API 앱키와 앱시크릿을 발급받아야 합니다.
- 모의투자와 실전투자는 API 서버와 TR ID가 다릅니다. 이 프로젝트는 `KIS_ENV` 값으로 자동 구분합니다.
- 주문 기능은 계좌 권한, 장 운영 시간, 예수금, 보유 수량에 따라 실패할 수 있습니다.
- 해외 주문은 거래소 코드가 시세 조회용(`NAS`)과 주문용(`NASD`)으로 다를 수 있습니다.
- 자동매매 스케줄러는 계속 실행되는 프로그램입니다. 종료하려면 터미널에서 `Ctrl + C`를 누르세요.

## 보안 주의

- `.env` 파일과 토큰 캐시 파일은 깃에 올리지 마세요.
- 실전투자(`KIS_ENV=real`)로 바꾸기 전에 주문 종목, 수량, 시간을 반드시 확인하세요.
- 테스트 중에는 주문 수량을 1주처럼 작게 두는 것을 권장합니다.
