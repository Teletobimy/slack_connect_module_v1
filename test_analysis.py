# -*- coding: utf-8 -*-
"""
터미널에서 직접 실행 가능한 분석 테스트 스크립트
Streamlit 없이 진행률과 로그를 터미널에서 확인할 수 있습니다.
"""

import os
import sys
import io
from datetime import datetime
from channel_report import SlackChannelReporter

# Windows 콘솔 인코딩 문제 해결 (UTF-8 강제 적용)
if sys.platform == "win32":
    # UTF-8 인코딩 강제 설정
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    # PowerShell UTF-8 설정
    os.system('chcp 65001 >nul 2>&1')


def main():
    """메인 함수"""
    try:
        print("=" * 80, flush=True)
        print("🧪 Slack 업무 분석 테스트 스크립트", flush=True)
        print("=" * 80, flush=True)
        print(flush=True)
    except Exception as e:
        print(f"출력 오류: {e}", file=sys.stderr)
        return
    
    # 환경 변수 확인
    user_token = os.getenv("SLACK_USER_TOKEN")
    openai_api_key = os.getenv("OPENAI_API_KEY")
    db_connection_string = os.getenv("DB_CONNECTION_STRING")
    
    if not user_token:
        print("❌ SLACK_USER_TOKEN 환경 변수가 설정되지 않았습니다.")
        print("\n설정 방법:")
        print("1. Windows PowerShell:")
        print('   $env:SLACK_USER_TOKEN="xoxp-your-token"')
        print('   $env:OPENAI_API_KEY="sk-your-api-key"')
        print('   $env:DB_CONNECTION_STRING="postgresql://postgres:password@host:5432/postgres"')
        return
    
    if not openai_api_key:
        print("⚠️ OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
        print("GPT 분석 없이 진행합니다.")
    
    if not db_connection_string:
        print("⚠️ DB_CONNECTION_STRING 환경 변수가 설정되지 않았습니다.")
        print("DB 저장 없이 진행합니다.")
    
    print("✅ 환경 변수 확인 완료")
    print(f"   - Slack Token: {'설정됨' if user_token else '없음'}")
    print(f"   - OpenAI API Key: {'설정됨' if openai_api_key else '없음'}")
    print(f"   - DB Connection: {'설정됨' if db_connection_string else '없음'}")
    print()
    
    try:
        # 리포트 생성기 초기화
        print("🔧 SlackChannelReporter 초기화 중...")
        reporter = SlackChannelReporter(
            user_token=user_token,
            openai_api_key=openai_api_key,
            db_connection_string=db_connection_string
        )
        print("✅ 초기화 완료")
        print()
        
        # 진행률 및 로그 콜백 설정 (터미널용)
        last_progress_status = ""
        
        def print_progress(progress: float, status: str):
            """진행률 터미널 출력"""
            nonlocal last_progress_status
            bar_length = 30
            filled = int(bar_length * progress)
            bar = "█" * filled + "░" * (bar_length - filled)
            percentage = int(progress * 100)
            current_status = f"[{bar}] {percentage:3d}% - {status}"
            
            # 진행률이 업데이트될 때만 출력 (같은 줄에 덮어쓰기)
            if current_status != last_progress_status:
                print(f"\r{current_status:<80}", end="", flush=True)
                last_progress_status = current_status
        
        def print_log(message: str):
            """로그 터미널 출력"""
            # 진행률 바 다음 줄에 로그 출력
            print()  # 진행률 바 줄 종료
            print(message, flush=True)
        
        # 콜백 설정
        reporter.progress_callback = print_progress
        reporter.log_callback = print_log
        
        print("=" * 80)
        print("🚀 분석 시작!")
        print("=" * 80)
        print()
        
        # 분석 실행
        start_time = datetime.now()
        reporter.generate_weekly_analysis_report()
        end_time = datetime.now()
        
        elapsed = (end_time - start_time).total_seconds()
        
        print()
        print("=" * 80)
        print(f"✅ 분석 완료! (소요 시간: {elapsed:.1f}초)")
        print("=" * 80)
        print()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

