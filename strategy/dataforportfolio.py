"""KIS 데이터를 수집해 조합을 분석하고 최종 포트폴리오까지 확정한다.

전체 실행 흐름
--------------
1. KIS에서 한국·미국 ETF와 USD/KRW 일별 원본을 수집한다.
2. 기간·중복·결측·가격 관계를 검증하고 모든 가격을 원화로 통일한다.
3. 공통 금요일 기준 주간 수익률과 495개 동일비중 조합을 분석한다.
4. 종목별 10~40% 제약 아래 최소분산 조합과 비중을 최종 확정한다.
5. 표·차트·분석 명세와 selected_portfolio.json을 저장한다.

실행 예시
---------
python strategy/dataforportfolio.py collect
python strategy/dataforportfolio.py analyze
python strategy/dataforportfolio.py run
python strategy/dataforportfolio.py validate

미국 ETF는 각 거래일 당시의 USD/KRW 환율로 원화 환산한다.
주문 API는 이 파일에서 호출하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import combinations, product
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")

# Windows consoles configured for CP949 cannot print every Unicode character.
# Preserve the validation run by escaping unsupported characters in log output.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

from matplotlib import pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import PercentFormatter


# =============================================================================
# 1. 프로젝트 경로와 KIS 조회 모듈 연결
# =============================================================================

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from kis import kis_client  # noqa: E402
from kis.kis_auth import issue_access_token  # noqa: E402


# =============================================================================
# 2. 분석 후보군, 파일 경로, 데이터 수집 기준
# =============================================================================

@dataclass(frozen=True)
class Candidate:
    """수집과 분석 전 과정에서 공통으로 사용하는 ETF 기본 정보."""

    symbol: str
    name: str
    country: str
    currency: str


CANDIDATES = (
    Candidate("069500", "KODEX 200", "KR", "KRW"),
    Candidate("226490", "KODEX 코스피", "KR", "KRW"),
    Candidate("292190", "KODEX KRX300", "KR", "KRW"),
    Candidate("229200", "KODEX KOSDAQ150", "KR", "KRW"),
    Candidate("226980", "KODEX 200중소형", "KR", "KRW"),
    Candidate("275290", "KODEX 가치주", "KR", "KRW"),
    Candidate("IVV", "iShares Core S&P 500 ETF", "US", "USD"),
    Candidate("ITOT", "iShares Core S&P Total US Market ETF", "US", "USD"),
    Candidate("IWM", "iShares Russell 2000 ETF", "US", "USD"),
    Candidate("IJS", "iShares S&P Small-Cap 600 Value ETF", "US", "USD"),
    Candidate("IWD", "iShares Russell 1000 Value ETF", "US", "USD"),
    Candidate("IWF", "iShares Russell 1000 Growth ETF", "US", "USD"),
)

DATA_DIR = Path(__file__).parent / "portfolio_data"
RAW_DIR = DATA_DIR / "raw"
ANALYSIS_DIR = DATA_DIR / "analysis"
MANIFEST_FILE = ANALYSIS_DIR / "analysis_manifest.json"
SELECTED_PORTFOLIO_FILE = ANALYSIS_DIR / "selected_portfolio.json"

ANALYSIS_YEARS = 5
REQUEST_DELAY = 0.7
RATE_LIMIT_RETRIES = 3
FX_JOIN_TOLERANCE_DAYS = 5
MAX_FX_MISSING_RATE = 0.01
WEEKS_PER_YEAR = 52

KR_DAILY = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
KR_DAILY_TR = "FHKST03010100"
US_DAILY = "/uapi/overseas-price/v1/quotations/dailyprice"
US_DAILY_TR = "HHDFS76240000"
US_PRICE = "/uapi/overseas-price/v1/quotations/price"
US_PRICE_TR = "HHDFS00000300"
FX_DAILY = "/uapi/overseas-price/v1/quotations/inquire-daily-chartprice"
FX_DAILY_TR = "FHKST03030100"
US_EXCHANGES = ("NAS", "NYS", "AMS")
FX_SYMBOL = "FX@KRW"  # frgn_code.mst: 원/달러(KMB)

# 사용자 제공 KIS 문서 이미지 기준: 0=수정주가, 1=원주가
KR_ADJUSTED_PRICE = "0"
US_ADJUSTED_PRICE = "1"


# =============================================================================
# 3. 분석 기간, KIS 재시도, 응답·파일 정규화
# =============================================================================

def analysis_window(end: date | None = None) -> tuple[date, date]:
    """최근 완결 금요일을 종료일로 하는 5년 구간을 반환한다."""
    if end is None:
        today = date.today()
        end = today - timedelta(days=(today.weekday() - 4) % 7)
        if end >= today:
            end -= timedelta(days=7)
    try:
        start = end.replace(year=end.year - ANALYSIS_YEARS)
    except ValueError:  # 2월 29일이면 2월 28일을 사용한다.
        start = end.replace(year=end.year - ANALYSIS_YEARS, day=28)
    return start, end


def api_get(token: str, endpoint: str, tr_id: str, params: dict) -> dict:
    """조회 API의 호출 제한만 짧게 재시도하고 다른 오류는 즉시 전달한다."""
    for attempt in range(RATE_LIMIT_RETRIES):
        response = kis_client.get(endpoint, tr_id, token, params)
        time.sleep(REQUEST_DELAY)
        if str(response.get("rt_cd", "")) == "0":
            return response
        if response.get("msg_cd") == "EGW00201" and attempt < RATE_LIMIT_RETRIES - 1:
            wait_seconds = 2 * (attempt + 1)
            print(f"KIS 호출 제한: {wait_seconds}초 후 재시도")
            time.sleep(wait_seconds)
            continue
        raise RuntimeError(
            f"KIS 오류: {response.get('msg_cd', '')} / {response.get('msg1', '')}"
        )
    raise RuntimeError("KIS 호출 제한 재시도 횟수를 초과했습니다.")


def response_rows(response: dict) -> list[dict]:
    output = response.get("output2", [])
    if isinstance(output, dict):
        return [output]
    return output if isinstance(output, list) else []


def number(value) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return float("nan")


def price_path(candidate: Candidate) -> Path:
    return RAW_DIR / candidate.country.lower() / f"{candidate.symbol}.csv"


def fx_path() -> Path:
    return RAW_DIR / "fx" / "USDKRW.csv"


def save_csv(records: list[dict], path: Path) -> None:
    """날짜 중복을 제거한 원본 데이터를 오래된 날짜부터 저장한다."""
    frame = pd.DataFrame(records).drop_duplicates("date").sort_values("date")
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


# =============================================================================
# 4. 한국·미국 ETF와 USD/KRW 일별 원본 수집
# =============================================================================

def collect_kr(token: str, candidate: Candidate, start: date, end: date) -> list[dict]:
    """국내 일봉을 최신 구간부터 과거 방향으로 이동하며 수집한다."""
    result: list[dict] = []
    cursor = end

    while cursor >= start:
        response = api_get(
            token,
            KR_DAILY,
            KR_DAILY_TR,
            {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": candidate.symbol,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": cursor.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": KR_ADJUSTED_PRICE,
            },
        )
        page = response_rows(response)
        if not page:
            break
        result.extend(
            {
                "date": datetime.strptime(row["stck_bsop_date"], "%Y%m%d").date(),
                "open": number(row.get("stck_oprc")),
                "high": number(row.get("stck_hgpr")),
                "low": number(row.get("stck_lwpr")),
                "close": number(row.get("stck_clpr")),
                "volume": number(row.get("acml_vol")),
                "exchange": "KRX",
            }
            for row in page
        )
        oldest = min(row["date"] for row in result)
        if oldest <= start:
            break
        # 다음 페이지 종료일을 가장 오래된 날짜보다 하루 앞당겨 반복을 막는다.
        cursor = oldest - timedelta(days=1)

    return [row for row in result if start <= row["date"] <= end]


def find_us_exchange(token: str, symbol: str) -> str:
    """시세가 존재하는 KIS 미국 거래소 코드를 NAS/NYS/AMS 순으로 찾는다."""
    for exchange in US_EXCHANGES:
        try:
            response = api_get(
                token,
                US_PRICE,
                US_PRICE_TR,
                {"AUTH_CODE": "", "EXCD": exchange, "SYMB": symbol},
            )
        except RuntimeError:
            continue
        if number(response.get("output", {}).get("last")) > 0:
            return exchange
    raise RuntimeError(f"{symbol}: KIS 거래소 코드를 찾지 못했습니다.")


def collect_us(
    token: str,
    candidate: Candidate,
    exchange: str,
    start: date,
    end: date,
) -> list[dict]:
    """미국 수정 일봉을 최신 구간부터 과거 방향으로 수집한다."""
    result: list[dict] = []
    cursor = end

    while cursor >= start:
        response = api_get(
            token,
            US_DAILY,
            US_DAILY_TR,
            {
                "AUTH": "",
                "EXCD": exchange,
                "SYMB": candidate.symbol,
                "GUBN": "0",
                "BYMD": cursor.strftime("%Y%m%d"),
                "MODP": US_ADJUSTED_PRICE,
            },
        )
        page = response_rows(response)
        if not page:
            break
        result.extend(
            {
                "date": datetime.strptime(row["xymd"], "%Y%m%d").date(),
                "open": number(row.get("open")),
                "high": number(row.get("high")),
                "low": number(row.get("low")),
                "close": number(row.get("clos")),
                "volume": number(row.get("tvol")),
                "exchange": exchange,
            }
            for row in page
        )
        oldest = min(row["date"] for row in result)
        if oldest <= start:
            break
        cursor = oldest - timedelta(days=1)

    return [row for row in result if start <= row["date"] <= end]


def collect_fx(token: str, symbol: str, start: date, end: date) -> list[dict]:
    """USD/KRW의 각 시점 환율을 수집한다. symbol은 KIS 환율 종목코드다."""
    result: list[dict] = []
    cursor = end

    while cursor >= start:
        response = api_get(
            token,
            FX_DAILY,
            FX_DAILY_TR,
            {
                "FID_COND_MRKT_DIV_CODE": "X",
                "FID_INPUT_ISCD": symbol,
                "FID_INPUT_DATE_1": start.strftime("%Y%m%d"),
                "FID_INPUT_DATE_2": cursor.strftime("%Y%m%d"),
                "FID_PERIOD_DIV_CODE": "D",
            },
        )
        page = response_rows(response)
        if not page:
            break
        result.extend(
            {
                "date": datetime.strptime(row["stck_bsop_date"], "%Y%m%d").date(),
                "close": number(row.get("ovrs_nmix_prpr")),
                "symbol": symbol,
            }
            for row in page
        )
        oldest = min(row["date"] for row in result)
        if oldest <= start:
            break
        cursor = oldest - timedelta(days=1)

    return [row for row in result if start <= row["date"] <= end]


def collect_all(fx_symbol: str, end: date | None = None) -> None:
    """후보군과 환율을 모두 수집하고 하나라도 실패하면 전체 실패로 처리한다."""
    start, end = analysis_window(end)
    token = issue_access_token()
    failures: list[str] = []
    print(f"수집기간: {start} ~ {end}")

    for candidate in CANDIDATES:
        try:
            if candidate.country == "KR":
                records = collect_kr(token, candidate, start, end)
            else:
                exchange = find_us_exchange(token, candidate.symbol)
                records = collect_us(token, candidate, exchange, start, end)
            if not records:
                raise RuntimeError("수집된 데이터가 없습니다.")
            save_csv(records, price_path(candidate))
            print(f"PASS {candidate.symbol:<6} {len(records):>4}행")
        except Exception as exc:
            failures.append(candidate.symbol)
            print(f"FAIL {candidate.symbol:<6} {exc}")

    try:
        records = collect_fx(token, fx_symbol, start, end)
        if not records:
            raise RuntimeError("수집된 환율 데이터가 없습니다.")
        save_csv(records, fx_path())
        print(f"PASS USDKRW {len(records):>4}행")
    except Exception as exc:
        failures.append("USDKRW")
        print(f"FAIL USDKRW {exc}")

    if failures:
        raise RuntimeError("수집 실패: " + ", ".join(failures))


# =============================================================================
# 5. 원본 품질검사, 환율 결합, 공통 주간 가격표 생성
# =============================================================================

def validate_frame(frame: pd.DataFrame, label: str, start: date, end: date) -> None:
    """분석 전에 필수 열·기간·중복·가격 이상 여부를 검사한다."""
    required = {"date", "close"}
    if not required.issubset(frame.columns):
        raise ValueError(f"{label}: 필수 열이 없습니다: {required - set(frame.columns)}")
    if frame.empty:
        raise ValueError(f"{label}: 데이터가 없습니다.")
    if frame["date"].duplicated().any():
        raise ValueError(f"{label}: 날짜 중복이 있습니다.")
    if frame["close"].isna().any() or (frame["close"] <= 0).any():
        raise ValueError(f"{label}: 종가 결측 또는 0 이하 값이 있습니다.")
    ohlc = {"open", "high", "low", "close"}
    if ohlc.issubset(frame.columns):
        if frame[list(ohlc)].isna().any().any():
            raise ValueError(f"{label}: OHLC 결측이 있습니다.")
        invalid_ohlc = (
            frame["high"] < frame[["open", "close", "low"]].max(axis=1)
        ) | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        if invalid_ohlc.any():
            dates = ", ".join(
                frame.loc[invalid_ohlc, "date"].dt.strftime("%Y-%m-%d").head(3)
            )
            print(
                f"WARN {label}: 수정주가 OHLC 관계 오류 "
                f"{int(invalid_ohlc.sum())}건 ({dates}) — 종가 분석은 계속"
            )
    first, last = frame["date"].min().date(), frame["date"].max().date()
    if first > start + timedelta(days=14):
        raise ValueError(f"{label}: 5년 시작 구간이 부족합니다 ({first}).")
    if last < end - timedelta(days=14):
        raise ValueError(f"{label}: 최근 구간이 부족합니다 ({last}).")


def read_validated(path: Path, label: str, start: date, end: date) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{label}: 파일이 없습니다: {path}")
    frame = pd.read_csv(path, parse_dates=["date"])
    validate_frame(frame, label, start, end)
    return frame.sort_values("date")


def build_weekly_prices(start: date, end: date) -> tuple[pd.DataFrame, float, str]:
    """모든 가격을 원화로 바꾸고 금요일 기준 주간 가격표를 만든다."""
    fx = read_validated(fx_path(), "USDKRW", start, end)[["date", "close", "symbol"]]
    fx = fx.rename(columns={"close": "fx"}).sort_values("date")
    series: dict[str, pd.Series] = {}

    for candidate in CANDIDATES:
        frame = read_validated(price_path(candidate), candidate.symbol, start, end)
        if candidate.country == "US":
            # 미래 환율을 쓰지 않도록 같은 날 또는 직전 5일 이내 환율만 연결한다.
            frame = pd.merge_asof(
                frame.sort_values("date"),
                fx[["date", "fx"]],
                on="date",
                direction="backward",
                tolerance=pd.Timedelta(days=FX_JOIN_TOLERANCE_DAYS),
            )
            missing = int(frame["fx"].isna().sum())
            missing_rate = missing / len(frame)
            if missing_rate > MAX_FX_MISSING_RATE:
                raise ValueError(
                    f"{candidate.symbol}: 당시 환율 연결 실패 "
                    f"{missing}건({missing_rate:.2%})"
                )
            if missing:
                print(
                    f"WARN {candidate.symbol}: 한국 휴장일 환율 미연결 "
                    f"{missing}건({missing_rate:.2%}) 제외"
                )
                frame = frame.dropna(subset=["fx"])
            frame["price_krw"] = frame["close"] * frame["fx"]
        else:
            frame["price_krw"] = frame["close"]

        weekly = frame.set_index("date")["price_krw"].resample("W-FRI").last()
        series[candidate.symbol] = weekly

    # 모든 후보가 동시에 존재하는 주만 남겨 공분산 비교의 날짜 기준을 통일한다.
    prices = pd.DataFrame(series).dropna()
    if len(prices) < 240:
        raise ValueError(f"공통 주간 관측치가 부족합니다: {len(prices)}개")
    return prices, float(fx.iloc[-1]["fx"]), str(fx.iloc[-1]["symbol"])


# =============================================================================
# 6. 개별 자산과 4종목 동일비중 조합의 탐색용 통계
# =============================================================================

def calculate_metrics(prices: pd.DataFrame, returns: pd.DataFrame) -> pd.DataFrame:
    """개별 종목의 연환산 수익·변동성·낙폭·상관관계를 계산한다."""
    metrics: list[dict] = []
    for symbol in prices.columns:
        values = prices[symbol]
        annual_return = (values.iloc[-1] / values.iloc[0]) ** (
            WEEKS_PER_YEAR / (len(values) - 1)
        ) - 1
        volatility = returns[symbol].std() * np.sqrt(WEEKS_PER_YEAR)
        drawdown = values / values.cummax() - 1
        metrics.append(
            {
                "symbol": symbol,
                "annual_return": annual_return,
                "annual_volatility": volatility,
                "max_drawdown": drawdown.min(),
                "sharpe_zero_rate": annual_return / volatility if volatility else np.nan,
                "average_correlation": returns.corr()[symbol].drop(symbol).mean(),
                "weekly_observations": len(values),
            }
        )
    return pd.DataFrame(metrics).set_index("symbol")


def calculate_combination_metrics(returns: pd.DataFrame) -> pd.DataFrame:
    """탐색용으로 12개 중 4개인 495개 조합을 동일가중 비교한다."""
    candidate_map = {candidate.symbol: candidate for candidate in CANDIDATES}
    annual_cov = returns.cov() * WEEKS_PER_YEAR
    annual_mean = returns.mean() * WEEKS_PER_YEAR
    correlation = returns.corr()
    records: list[dict] = []

    for symbols in combinations(returns.columns, 4):
        weights = np.full(4, 0.25)
        covariance = annual_cov.loc[list(symbols), list(symbols)].to_numpy()
        volatility = float(np.sqrt(weights @ covariance @ weights))
        expected_return = float(weights @ annual_mean.loc[list(symbols)].to_numpy())
        combination_returns = returns.loc[:, list(symbols)] @ weights
        wealth = (1 + combination_returns).cumprod()
        pair_corr = correlation.loc[list(symbols), list(symbols)].to_numpy()
        average_pair_corr = float(pair_corr[np.triu_indices(4, k=1)].mean())
        records.append(
            {
                "combination": "|".join(symbols),
                "symbols": ",".join(symbols),
                "kr_count": sum(candidate_map[symbol].country == "KR" for symbol in symbols),
                "us_count": sum(candidate_map[symbol].country == "US" for symbol in symbols),
                "annual_return": expected_return,
                "annual_volatility": volatility,
                "sharpe_zero_rate": expected_return / volatility if volatility else np.nan,
                "max_drawdown": float((wealth / wealth.cummax() - 1).min()),
                "average_pair_correlation": average_pair_corr,
            }
        )
    return pd.DataFrame(records).sort_values("annual_volatility").reset_index(drop=True)


# =============================================================================
# 7. 실제 주문에 전달할 제한 비중 최소분산 포트폴리오 확정
# =============================================================================

def weight_grid() -> np.ndarray:
    """종목별 10~40%, 5% 간격이며 합계가 100%인 비중 후보다."""
    levels = np.arange(0.10, 0.401, 0.05)
    return np.array(
        [weights for weights in product(levels, repeat=4) if np.isclose(sum(weights), 1.0)]
    )


def select_minimum_variance_portfolio(
    returns: pd.DataFrame, universe: list[dict], as_of: date
) -> dict:
    """한미 혼합 4종목과 제한 비중을 함께 탐색해 최소분산 대상을 확정한다."""
    universe_by_symbol = {item["symbol"]: item for item in universe}
    covariance = returns.cov() * WEEKS_PER_YEAR
    expected_returns = returns.mean() * WEEKS_PER_YEAR
    grids = weight_grid()
    best: tuple[tuple[str, ...], np.ndarray, float, float] | None = None

    for symbols in combinations(returns.columns, 4):
        # 한 국가에만 치우친 조합을 제외하고 한국·미국이 모두 포함되게 한다.
        if {universe_by_symbol[symbol]["country"] for symbol in symbols} != {"KR", "US"}:
            continue
        matrix = covariance.loc[list(symbols), list(symbols)].to_numpy()
        # 모든 허용 비중의 w'Σw를 벡터화해 해당 조합의 최소분산 비중을 찾는다.
        variances = np.einsum("ij,jk,ik->i", grids, matrix, grids)
        index = int(np.argmin(variances))
        volatility = float(np.sqrt(variances[index]))
        annual_return = float(
            grids[index] @ expected_returns.loc[list(symbols)].to_numpy()
        )
        if best is None or volatility < best[2]:
            best = symbols, grids[index].copy(), volatility, annual_return

    if best is None:
        raise RuntimeError("제약조건을 만족하는 포트폴리오가 없습니다.")
    symbols, weights, volatility, annual_return = best
    return {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "data_quality": "PASS",
        "method": "minimum_variance_grid_5pct",
        "expected_return": annual_return,
        "expected_volatility": volatility,
        "portfolio": [
            {**universe_by_symbol[symbol], "weight": round(float(weight), 4)}
            for symbol, weight in zip(symbols, weights)
        ],
    }


# =============================================================================
# 8. 상관관계·위험수익·누적수익률 시각화
# =============================================================================

def create_charts(
    prices: pd.DataFrame,
    metrics: pd.DataFrame,
    correlation: pd.DataFrame,
    combination_metrics: pd.DataFrame,
) -> None:
    """상관관계, 위험-수익률, 누적수익률을 PNG로 저장한다."""
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white"})

    colors = LinearSegmentedColormap.from_list(
        "orange_white_blue", ["#d97706", "#f8fafc", "#2563eb"]
    )
    fig, ax = plt.subplots(figsize=(10, 8))
    image = ax.imshow(correlation, vmin=-1, vmax=1, cmap=colors)
    ax.set_xticks(range(len(correlation)), correlation.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(correlation)), correlation.index)
    ax.set_title("Return Correlation Matrix", pad=16, color="#172033")
    for row in range(len(correlation)):
        for column in range(len(correlation)):
            ax.text(
                column,
                row,
                f"{correlation.iloc[row, column]:.2f}",
                ha="center",
                va="center",
                fontsize=7,
                color="white" if abs(correlation.iloc[row, column]) >= 0.6 else "#172033",
            )
    fig.colorbar(image, ax=ax, label="Correlation")
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "correlation_heatmap.png", dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 7))
    ax.scatter(
        combination_metrics["annual_volatility"],
        combination_metrics["annual_return"],
        s=18,
        alpha=0.35,
        color="#2563eb",
        label="4-asset equal-weight combinations",
    )
    ax.scatter(
        metrics["annual_volatility"],
        metrics["annual_return"],
        s=55,
        color="#d97706",
        edgecolor="#172033",
        linewidth=0.5,
        label="Individual assets",
    )
    ordered_labels = list(metrics.sort_values("annual_return").iterrows())
    return_span = metrics["annual_return"].max() - metrics["annual_return"].min()
    minimum_gap = max(return_span * 0.035, 0.0025)
    label_y: list[float] = []
    for _, row in ordered_labels:
        position = float(row["annual_return"])
        if label_y and position < label_y[-1] + minimum_gap:
            position = label_y[-1] + minimum_gap
        label_y.append(position)
    overflow = max(0.0, label_y[-1] - metrics["annual_return"].max())
    label_y = [position - overflow for position in label_y]

    volatility_midpoint = metrics["annual_volatility"].median()
    risk_span = metrics["annual_volatility"].max() - metrics["annual_volatility"].min()
    for (symbol, row), y_position in zip(ordered_labels, label_y):
        align_left = row["annual_volatility"] <= volatility_midpoint
        x_position = row["annual_volatility"] + (0.025 if align_left else -0.025) * risk_span
        ax.annotate(
            symbol,
            (row["annual_volatility"], row["annual_return"]),
            xytext=(x_position, y_position),
            textcoords="data",
            ha="left" if align_left else "right",
            va="center",
            fontsize=8,
            arrowprops={"arrowstyle": "-", "color": "#7b8494", "lw": 0.5},
        )
    ax.set_title("Risk and Return Comparison", pad=16, color="#172033")
    ax.set_xlabel("Annualized volatility")
    ax.set_ylabel("Annualized return")
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.yaxis.set_major_formatter(PercentFormatter(1))
    ax.grid(color="#d8dee9", linewidth=0.7, alpha=0.7)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "risk_return_scatter.png", dpi=160)
    plt.close(fig)

    cumulative = prices.div(prices.iloc[0]).sub(1)
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), sharey=True)
    for ax, country in zip(axes, ("KR", "US")):
        symbols = [c.symbol for c in CANDIDATES if c.country == country]
        palette = plt.cm.Blues(np.linspace(0.4, 0.9, len(symbols)))
        for symbol, color in zip(symbols, palette):
            ax.plot(cumulative.index, cumulative[symbol], label=symbol, color=color, linewidth=1.5)
        ax.set_title(f"{country} ETF cumulative returns", color="#172033")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.grid(color="#d8dee9", linewidth=0.7, alpha=0.7)
        ax.legend(frameon=False, ncol=2, fontsize=8)
    axes[0].set_ylabel("Cumulative return in KRW")
    fig.suptitle("Five-Year Cumulative Returns", color="#172033")
    fig.tight_layout()
    fig.savefig(ANALYSIS_DIR / "cumulative_returns.png", dpi=160)
    plt.close(fig)


# =============================================================================
# 9. 분석 파이프라인 실행과 산출물 저장
# =============================================================================

def analyze(end: date | None = None) -> dict:
    """검증된 로컬 원본에서 통계·조합·최종 목표 파일을 한 번에 만든다."""
    start, end = analysis_window(end)
    prices, latest_fx, fx_symbol = build_weekly_prices(start, end)
    returns = prices.pct_change().dropna()
    metrics = calculate_metrics(prices, returns)
    correlation = returns.corr()
    # 동일비중 495개 표는 비교·진단용이며 실제 주문 비중과는 구분한다.
    combination_metrics = calculate_combination_metrics(returns)

    exchanges = {}
    for candidate in CANDIDATES:
        frame = pd.read_csv(price_path(candidate))
        exchanges[candidate.symbol] = str(frame["exchange"].dropna().iloc[-1])

    universe = [
        {
            "country": candidate.country,
            "symbol": candidate.symbol,
            "name": candidate.name,
            "exchange": exchanges[candidate.symbol],
        }
        for candidate in CANDIDATES
    ]
    # 실제 주문 파일이 읽을 유일한 최종 조합과 비중은 여기서 확정한다.
    selected = select_minimum_variance_portfolio(returns, universe, end)

    manifest = {
        "as_of": end.isoformat(),
        "analysis_start": start.isoformat(),
        "analysis_end": end.isoformat(),
        "base_currency": "KRW",
        "fx_method": "historical_daily_usdkrw_backward_5d",
        "fx_symbol": fx_symbol,
        "latest_fx": latest_fx,
        "price_frequency": "W-FRI",
        "data_quality": "PASS",
        "universe": universe,
        "outputs": {
            "weekly_prices": "weekly_prices_krw.csv",
            "weekly_returns": "weekly_returns.csv",
            "asset_metrics": "asset_metrics.csv",
            "correlation": "correlation.csv",
            "combination_metrics": "combination_metrics.csv",
            "selected_portfolio": SELECTED_PORTFOLIO_FILE.name,
        },
    }
    selected_payload = {**manifest, **selected}

    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(ANALYSIS_DIR / "asset_metrics.csv", encoding="utf-8-sig")
    correlation.to_csv(ANALYSIS_DIR / "correlation.csv", encoding="utf-8-sig")
    prices.to_csv(ANALYSIS_DIR / "weekly_prices_krw.csv", encoding="utf-8-sig")
    returns.to_csv(ANALYSIS_DIR / "weekly_returns.csv", encoding="utf-8-sig")
    combination_metrics.to_csv(
        ANALYSIS_DIR / "combination_metrics.csv", index=False, encoding="utf-8-sig"
    )
    SELECTED_PORTFOLIO_FILE.write_text(
        json.dumps(selected_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    create_charts(prices, metrics, correlation, combination_metrics)
    MANIFEST_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"분석 완료: {ANALYSIS_DIR}")
    print(f"조합 비교: {len(combination_metrics)}개")
    print(
        "최종 선택: "
        + ", ".join(
            f"{item['symbol']} {item['weight']:.0%}"
            for item in selected_payload["portfolio"]
        )
    )
    return manifest


# =============================================================================
# 10. 데이터 검증 명령과 명령행 인터페이스
# =============================================================================

def validate_only(end: date | None = None) -> None:
    """분석 산출물을 만들지 않고 모든 원본 파일의 품질만 확인한다."""
    start, end = analysis_window(end)
    for candidate in CANDIDATES:
        read_validated(price_path(candidate), candidate.symbol, start, end)
        print(f"PASS {candidate.symbol}")
    read_validated(fx_path(), "USDKRW", start, end)
    print("PASS USDKRW")


def parse_date(value: str | None) -> date | None:
    return datetime.strptime(value, "%Y-%m-%d").date() if value else None


def print_startup_guide() -> None:
    """옵션 없이 실행했을 때 데이터 수집·분석 명령을 안내한다."""
    print(
        """
[KIS 포트폴리오 데이터 수집·분석 사용설명서]

이 파일은 주문을 보내지 않습니다.
가격·환율 데이터를 수집하고 조합을 분석해 최종 목표 비중을 저장합니다.

가장 일반적인 실행
   python strategy/dataforportfolio.py run
   데이터 수집 → 검증 → 조합 분석 → 최종 비중 확정을 한 번에 실행합니다.

단계별 실행
   python strategy/dataforportfolio.py collect
   KIS에서 가격·환율 원본 데이터만 새로 수집합니다.

   python strategy/dataforportfolio.py analyze
   이미 수집된 로컬 데이터로 분석 파일만 다시 만듭니다.

   python strategy/dataforportfolio.py validate
   원본 데이터의 기간·중복·결측·가격 이상 여부만 검사합니다.

선택 옵션
   --end YYYY-MM-DD       분석 종료일을 지정합니다.
   --fx-symbol FX@KRW     USD/KRW 환율 종목코드를 지정합니다.

주요 결과
   strategy/portfolio_data/analysis/selected_portfolio.json
   portfolio.py는 이 파일의 최종 종목과 비중을 읽어 주문계획을 만듭니다.

Linux에서는 python 대신 python3를 사용하세요.
""".strip()
    )


def main() -> None:
    if len(sys.argv) == 1:
        print_startup_guide()
        return

    parser = argparse.ArgumentParser(description="KIS 포트폴리오 데이터 수집·분석")
    parser.add_argument("command", choices=("collect", "analyze", "run", "validate"))
    parser.add_argument("--end", help="분석 종료일 YYYY-MM-DD")
    parser.add_argument(
        "--fx-symbol",
        default=FX_SYMBOL,
        help=f"KIS USD/KRW 환율 종목코드, 기본값 {FX_SYMBOL}",
    )
    args = parser.parse_args()
    end = parse_date(args.end)

    if args.command in {"collect", "run"}:
        collect_all(args.fx_symbol, end)
    if args.command in {"analyze", "run"}:
        analyze(end)
    if args.command == "validate":
        validate_only(end)


if __name__ == "__main__":
    main()
