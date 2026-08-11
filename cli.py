"""
파일명: cli.py
역할: PC 터미널 환경에서 사용자가 직접 메뉴를 선택하여 
      주식 잔고, 현재가 시세, 체결 내역을 조회할 수 있는 대화형(CLI) 프로그램
실행: python cli.py
"""

import sys
import time
from kis_auth import issue_access_token
import kis_domestic_stock as domestic
import kis_overseas_stock as overseas
import kis_formatter as formatter


def display_menu() -> None:
    """메인 메뉴 항목을 콘솔에 출력합니다."""
    print("\n" + "=" * 55)
    print("📊 한국투자증권 자동매매 상태조회 대시보드 (PC용)")
    print("=" * 55)
    print(" [1] 🇰🇷 국내주식 잔고 및 예수금 조회")
    print(" [2] 🇺🇸 해외주식 잔고 및 예수금 조회")
    print(" [3] 📈 국내주식 현재가 시세 조회")
    print(" [4] 📈 해외주식 현재가 시세 조회")
    print(" [5] 📜 오늘 주문 및 체결 내역 전체 조회")
    print(" [0] 🚪 프로그램 종료")
    print("=" * 55)


def run_cli() -> None:
    """사용자의 키보드 입력을 받아 각 조회 기능을 실행하는 대화형 루프입니다."""
    print("🚀 상태조회 프로그램을 시작합니다. 인증 토큰 확인 중...")
    
    try:
        # 최초 토큰 발급 확인 (유효하면 캐시된 토큰 사용)
        token = issue_access_token()
        print("✅ 인증 성공! 메뉴를 선택하세요.")
    except Exception as err:
        print(f"❌ 인증 실패: {err}")
        print(".env 파일의 KIS_APP_KEY 및 KIS_APP_SECRET을 확인해 주세요.")
        return

    while True:
        display_menu()
        choice = input("👉 원하시는 기능의 번호를 입력하세요 (0~5): ").strip()

        if choice == "0":
            print("\n👋 상태조회 프로그램을 종료합니다. 좋은 하루 되세요!")
            sys.exit(0)

        elif choice == "1":
            print("\n⏳ 국내주식 잔고를 조회하고 있습니다...")
            try:
                data = domestic.inquire_balance(token)
                result_text = formatter.format_domestic_balance(data)
                print(result_text)
            except Exception as exc:
                print(f"❌ 조회 중 오류 발생: {exc}")

        elif choice == "2":
            print("\n⏳ 해외주식 잔고 및 달러 예수금을 조회하고 있습니다...")
            try:
                data = overseas.inquire_balance(token)
                time.sleep(0.3)  # 모의투자 서버 초당 호출 제한 방지
                present_data = overseas.inquire_present_balance(token)
                result_text = formatter.format_overseas_balance(data, present_data)
                print(result_text)
            except Exception as exc:
                print(f"❌ 조회 중 오류 발생: {exc}")

        elif choice == "3":
            code = input("👉 조회할 국내 종목코드 6자리를 입력하세요 (예: 005930): ").strip()
            if not code:
                print("⚠️ 종목코드가 입력되지 않았습니다.")
                continue
            
            print(f"\n⏳ 국내 종목({code}) 시세를 조회하고 있습니다...")
            try:
                data = domestic.inquire_price(token, code)
                result_text = formatter.format_domestic_price(data, code)
                print(result_text)
            except Exception as exc:
                print(f"❌ 조회 중 오류 발생: {exc}")

        elif choice == "4":
            ticker = input("👉 조회할 해외 종목 티커를 입력하세요 (예: AAPL, TSLA): ").strip().upper()
            if not ticker:
                print("⚠️ 티커가 입력되지 않았습니다.")
                continue
            
            # 미국 주요 시세용 거래소 코드는 기본 NAS로 처리
            print(f"\n⏳ 해외 종목({ticker}) 시세를 조회하고 있습니다...")
            try:
                data = overseas.inquire_price(token, "NAS", ticker)
                result_text = formatter.format_overseas_price(data, ticker)
                print(result_text)
            except Exception as exc:
                print(f"❌ 조회 중 오류 발생: {exc}")

        elif choice == "5":
            print("\n⏳ 오늘 국내/해외 주문 및 체결 내역을 조회하고 있습니다...")
            try:
                # 국내 체결 내역
                dom_data = domestic.inquire_order_history(token)
                print("\n" + formatter.format_order_history(dom_data, title="국내주식 당일 주문/체결 내역"))
                
                # 해외 체결 내역
                ovs_data = overseas.inquire_order_history(token)
                print("\n" + formatter.format_order_history(ovs_data, title="해외주식 당일 주문/체결 내역"))
            except Exception as exc:
                print(f"❌ 체결 내역 조회 중 오류 발생: {exc}")

        else:
            print("⚠️ 잘못된 번호입니다. 0번에서 5번 사이의 숫자를 입력해 주세요.")


if __name__ == "__main__":
    run_cli()
