# -*- coding: utf-8 -*-
"""
Streamlit CEO 대시보드
Slack 채널별 담당자 메시지 분석 리포트를 CEO 친화적 UI로 표시
"""

import streamlit as st
import os
import time
from datetime import datetime, timedelta, timezone
import json
from channel_report import SlackChannelReporter
from typing import Dict, Any, Optional

# 페이지 설정
st.set_page_config(
    page_title="Slack 업무 분석 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# CSS 스타일링 (CEO 친화적 큰 폰트)
st.markdown("""
    <style>
    .big-font {
        font-size:48px !important;
        font-weight: bold;
    }
    .medium-font {
        font-size:32px !important;
        font-weight: bold;
    }
    .metric-container {
        background-color: #f0f2f6;
        padding: 20px;
        border-radius: 10px;
        margin: 10px 0;
    }
    </style>
    """, unsafe_allow_html=True)


def check_login():
    """로그인 상태 확인"""
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False
    return st.session_state['authenticated']


def login_page():
    """로그인 페이지"""
    st.title("🔐 Slack 업무 분석 대시보드")
    st.markdown("---")
    
    # Streamlit secrets에서 로그인 정보 가져오기
    login_username = st.secrets.get("LOGIN_USERNAME", "master")
    login_password = st.secrets.get("LOGIN_PASSWORD", "bnk1122*")
    
    username = st.text_input("사용자명", value="", key="login_username")
    password = st.text_input("비밀번호", type="password", value="", key="login_password")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        if st.button("로그인", type="primary", use_container_width=True):
            if username == login_username and password == login_password:
                st.session_state['authenticated'] = True
                st.rerun()
            else:
                st.error("❌ 사용자명 또는 비밀번호가 올바르지 않습니다.")


def get_reporter() -> Optional[SlackChannelReporter]:
    """SlackChannelReporter 인스턴스 생성"""
    import traceback
    
    # Secrets 확인 (디버그 정보는 expander 안에)
    user_token = st.secrets.get("SLACK_USER_TOKEN")
    openai_api_key = st.secrets.get("OPENAI_API_KEY")
    db_connection_string = st.secrets.get("DB_CONNECTION_STRING")
    
    # 디버그 정보를 접기/펼치기 가능한 expander로 감싸기
    with st.expander("🔍 [디버그 정보]", expanded=False):
        st.info("🔍 [디버그] 리포터 생성 시작...")
        st.info("🔍 [디버그] Step 1: Secrets 로드 중...")
        st.info(f"🔍 [디버그] - SLACK_USER_TOKEN: {'✅ 설정됨' if user_token else '❌ 없음'}")
        st.info(f"🔍 [디버그] - OPENAI_API_KEY: {'✅ 설정됨' if openai_api_key else '⚠️ 없음'}")
        st.info(f"🔍 [디버그] - DB_CONNECTION_STRING: {'✅ 설정됨' if db_connection_string else '⚠️ 없음'}")
    
    if not user_token:
        st.error("❌ SLACK_USER_TOKEN이 설정되지 않았습니다.")
        return None
    
    try:
        with st.expander("🔍 [디버그 정보]", expanded=False):
            st.info("🔍 [디버그] Step 2: SlackChannelReporter 인스턴스 생성 중...")
        
        reporter = SlackChannelReporter(
            user_token=user_token,
            openai_api_key=openai_api_key,
            db_connection_string=db_connection_string
        )
        
        with st.expander("🔍 [디버그 정보]", expanded=False):
            st.info("🔍 [디버그] Step 3: 리포터 객체 생성 완료!")
            
            # 속성 존재 확인 (여러 방법으로)
            st.info(f"🔍 [디버그] - hasattr(log_callback): {hasattr(reporter, 'log_callback')}")
            st.info(f"🔍 [디버그] - hasattr(progress_callback): {hasattr(reporter, 'progress_callback')}")
            
            # 직접 접근 시도
            try:
                lc = reporter.log_callback
                st.info(f"🔍 [디버그] - log_callback 직접 접근 성공: {type(lc)}")
            except AttributeError as attr_e:
                st.error(f"❌ [직접접근실패] log_callback 접근 시 AttributeError: {attr_e}")
                st.error(f"🔍 [디버그] reporter 객체 속성 목록:")
                st.code("\n".join([x for x in dir(reporter) if not x.startswith('_')]), language='text')
            
            # getattr로 접근 시도
            lc_getattr = getattr(reporter, 'log_callback', 'NOT_FOUND')
            st.info(f"🔍 [디버그] - getattr(log_callback): {lc_getattr}")
            
            if hasattr(reporter, 'log_callback'):
                st.info(f"🔍 [디버그] - log_callback 값: {reporter.log_callback}")
        
        return reporter
    except AttributeError as ae:
        with st.expander("🔍 [디버그 정보 - 오류]", expanded=True):
            st.error(f"❌ [AttributeError] 속성 오류 발생: {ae}")
            st.error(f"🔍 [디버그] 오류 발생 위치: {traceback.format_exc()}")
            st.code(traceback.format_exc(), language='python')
        return None
    except Exception as init_e:
        with st.expander("🔍 [디버그 정보 - 오류]", expanded=True):
            st.error(f"❌ [InitError] 초기화 중 오류: {init_e}")
            st.error(f"🔍 [디버그] 오류 타입: {type(init_e).__name__}")
            st.error(f"🔍 [디버그] 전체 스택 트레이스:")
            st.code(traceback.format_exc(), language='python')
        return None


def load_analyses_from_db(reporter: SlackChannelReporter) -> Dict[str, Dict]:
    """DB에서 분석 결과 로드 (월별)"""
    if not reporter:
        return {}
    if not hasattr(reporter, 'db_conn') or not reporter.db_conn:
        return {}
    
    # 현재 날짜 확인 (중간일 때 현재 달 숨기기)
    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst)
    current_month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    try:
        cursor = reporter.db_conn.cursor()
        cursor.execute("""
            SELECT ga.user_id, u.real_name, ga.week_start, ga.week_range, ga.analysis_text
            FROM gpt_analyses ga
            LEFT JOIN users u ON ga.user_id = u.id
            ORDER BY ga.week_start DESC, u.real_name
        """)
        
        results = {}
        for row in cursor.fetchall():
            user_id, user_name, month_start, month_range, analysis_text = row
            user_name = user_name or user_id
            
            # month_start가 date 객체인 경우 datetime으로 변환
            if isinstance(month_start, type(today.date())):
                month_start_dt = datetime.combine(month_start, datetime.min.time()).replace(tzinfo=kst)
            else:
                month_start_dt = month_start
            
            # 현재 달이고 15일 이전이면 스킵
            if month_start_dt.date() == current_month_start.date() and today.day < 15:
                continue
            
            if user_name not in results:
                results[user_name] = {}
            
            results[user_name][month_start] = {
                "month_range": month_range,
                "analysis": analysis_text,
                "month_start": month_start
            }
        
        cursor.close()
        return results
    except Exception as e:
        st.error(f"⚠️ DB 로드 오류: {e}")
        return {}


def main_dashboard():
    """메인 대시보드"""
    st.title("📊 Slack 업무 분석 대시보드")
    
    # 사이드바
    with st.sidebar:
        st.header("⚙️ 설정")
        
        if st.button("🔄 데이터 수집 및 분석 실행", use_container_width=True):
            st.session_state['analysis_running'] = True
            st.rerun()
        
        st.markdown("---")
        if st.button("🚪 로그아웃", use_container_width=True):
            st.session_state['authenticated'] = False
            st.rerun()
    
    # 분석 실행 중인 경우
    if st.session_state.get('analysis_running', False):
        reporter = get_reporter()
        if reporter:
            try:
                # 메인 영역에 진행률 바 및 상태 텍스트 생성
                st.header("🔄 데이터 수집 및 분석 실행 중...")
                
                # Supabase 연결 상태 확인 섹션
                st.subheader("🔌 Supabase 연결 상태")
                db_status_container = st.container()
                
                with db_status_container:
                    # 안전하게 속성 확인
                    db_conn = getattr(reporter, 'db_conn', None)
                    db_status = getattr(reporter, 'db_connection_status', '알 수 없음')
                    db_type = getattr(reporter, 'db_connection_type', None)
                    
                    if db_conn:
                        st.success(f"✅ 연결 성공: {db_status}")
                        if db_type:
                            st.info(f"연결 타입: {db_type}")
                        
                        # 테이블 존재 여부 확인
                        try:
                            cursor = db_conn.cursor()
                            cursor.execute("""
                                SELECT table_name 
                                FROM information_schema.tables 
                                WHERE table_schema = 'public'
                                ORDER BY table_name;
                            """)
                            tables = [row[0] for row in cursor.fetchall()]
                            cursor.close()
                            
                            required_tables = ['messages', 'channels', 'users', 'gpt_analyses']
                            existing_tables = [t for t in required_tables if t in tables]
                            missing_tables = [t for t in required_tables if t not in tables]
                            
                            if existing_tables:
                                st.success(f"✅ 테이블 확인: {len(existing_tables)}/{len(required_tables)}개 존재")
                            if missing_tables:
                                st.warning(f"⚠️ 테이블 누락: {', '.join(missing_tables)}")
                        except Exception as e:
                            st.warning(f"⚠️ 테이블 확인 실패: {str(e)[:100]}")
                    else:
                        st.error(f"❌ 연결 실패: {db_status}")
                
                st.markdown("---")
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # 로그를 저장할 리스트
                log_messages = []
                
                # 진행률 및 로그를 저장할 변수
                current_progress = 0.0
                current_status = "초기화 중..."
                
                def update_progress(progress_value: float, status: str):
                    """진행률 업데이트 콜백"""
                    nonlocal current_progress, current_status
                    current_progress = progress_value
                    current_status = status
                    progress_bar.progress(progress_value)
                    status_text.markdown(f"### 진행률: {int(progress_value * 100)}%")
                    status_text.caption(status)
                
                def log_message(message: str):
                    """로그 메시지 콜백"""
                    log_messages.append(message)
                    # 최근 200개만 유지 (메모리 절약)
                    if len(log_messages) > 200:
                        log_messages.pop(0)
                
                # 콜백 함수 설정 (안전하게 속성 확인 후 설정)
                if not hasattr(reporter, 'progress_callback'):
                    st.error("❌ reporter.progress_callback 속성이 없습니다!")
                    st.session_state['analysis_running'] = False
                    return
                if not hasattr(reporter, 'log_callback'):
                    st.error("❌ reporter.log_callback 속성이 없습니다!")
                    st.error(f"🔍 reporter 객체 속성: {[x for x in dir(reporter) if not x.startswith('_')]}")
                    st.session_state['analysis_running'] = False
                    return
                
                reporter.progress_callback = update_progress
                reporter.log_callback = log_message
                
                # 초기 진행률 표시
                progress_bar.progress(0)
                status_text.markdown("### 진행률: 0%")
                status_text.caption("🔄 시작 중... 잠시만 기다려주세요.")
                
                # 로그 표시 영역 (진행률 아래에 배치)
                st.markdown("---")
                st.subheader("📋 실시간 실행 로그")
                log_placeholder = st.empty()
                log_placeholder.info("📝 로그가 곧 표시됩니다. 분석이 진행 중입니다...")
                
                # 실시간 로그 업데이트를 위한 컨테이너
                log_display_container = st.container()
                
                # 분석 실행
                try:
                    # 분석 실행
                    reporter.generate_weekly_analysis_report()
                    
                    # 완료 후 최종 상태 표시
                    progress_bar.progress(1.0)
                    status_text.markdown("### ✅ 진행률: 100%")
                    status_text.caption("분석 완료!")
                    
                    # 최종 로그 표시 (반드시 표시)
                    if log_messages:
                        with log_display_container:
                            st.success(f"✅ 총 {len(log_messages)}개의 로그 메시지가 수집되었습니다.")
                            
                            # 최근 로그 표시
                            recent_logs = log_messages[-100:]
                            log_text = "\n".join(recent_logs)
                            log_placeholder.text_area(
                                "", 
                                value=log_text, 
                                height=400, 
                                label_visibility="collapsed", 
                                key="final_logs"
                            )
                            
                            # 전체 로그는 expander에
                            with st.expander("📋 전체 실행 로그 보기", expanded=False):
                                full_log_text = "\n".join(log_messages)
                                st.text_area(
                                    "", 
                                    value=full_log_text, 
                                    height=500, 
                                    label_visibility="collapsed", 
                                    key="full_logs"
                                )
                            
                            # DB 통계 표시 (안전하게 속성 확인)
                            st.markdown("---")
                            st.subheader("📊 DB 저장 통계")
                            
                            if hasattr(reporter, 'db_stats'):
                                db_stats = reporter.db_stats
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.metric("메시지 저장", f"{db_stats.get('messages_saved', 0)}개", 
                                             delta=f"-{db_stats.get('messages_failed', 0)}개 실패" if db_stats.get('messages_failed', 0) > 0 else None)
                                    st.metric("채널 저장", f"{db_stats.get('channels_saved', 0)}개",
                                             delta=f"-{db_stats.get('channels_failed', 0)}개 실패" if db_stats.get('channels_failed', 0) > 0 else None)
                                with col2:
                                    st.metric("사용자 저장", f"{db_stats.get('users_saved', 0)}개",
                                             delta=f"-{db_stats.get('users_failed', 0)}개 실패" if db_stats.get('users_failed', 0) > 0 else None)
                                    st.metric("GPT 분석 저장", f"{db_stats.get('analyses_saved', 0)}개",
                                             delta=f"-{db_stats.get('analyses_failed', 0)}개 실패" if db_stats.get('analyses_failed', 0) > 0 else None)
                            else:
                                st.warning("⚠️ DB 통계 정보를 가져올 수 없습니다.")
                    else:
                        log_placeholder.warning("⚠️ 로그 메시지가 수집되지 않았습니다. 콜백이 제대로 작동하지 않았을 수 있습니다.")
                    
                    # 완료 표시
                    st.success("✅ 분석 완료!")
                    st.balloons()
                    
                    st.session_state['analysis_running'] = False
                    time.sleep(3)  # 완료 메시지를 보여주기 위한 대기
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 분석 중 오류 발생: {e}")
                    import traceback
                    st.code(traceback.format_exc())
                    
                    # 오류 발생 시에도 로그 표시
                    if log_messages:
                        with log_display_container:
                            st.error(f"❌ 오류 발생! 수집된 로그: {len(log_messages)}개")
                            with st.expander("📋 오류 전 로그 보기", expanded=True):
                                log_text = "\n".join(log_messages)
                                st.text_area("", value=log_text, height=400, label_visibility="collapsed", key="error_logs")
                    else:
                        log_placeholder.error("❌ 오류가 발생했고 로그도 수집되지 않았습니다.")
                    
                    st.session_state['analysis_running'] = False
                
            except Exception as e:
                st.error(f"❌ 오류: {e}")
                import traceback
                st.code(traceback.format_exc())
                st.session_state['analysis_running'] = False
        else:
            st.session_state['analysis_running'] = False
        return
    
    # 리포터 초기화
    reporter = get_reporter()
    if not reporter:
        return
    
    # DB에서 분석 결과 로드
    analyses = load_analyses_from_db(reporter)
    
    if not analyses:
        st.info("📝 아직 분석된 데이터가 없습니다. 사이드바에서 '데이터 수집 및 분석 실행'을 클릭하세요.")
        return
    
    # 전체 요약 통계
    st.header("📈 전체 요약")
    total_users = len(analyses)
    total_months = sum(len(months) for months in analyses.values())
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("분석된 담당자 수", f"{total_users}명")
    with col2:
        st.metric("총 월 수", f"{total_months}개월")
    with col3:
        kst = timezone(timedelta(hours=9))
        today = datetime.now(kst)
        st.metric("오늘", today.strftime("%Y-%m-%d"))
    with col4:
        # 최근 업데이트 시간 (간단히 표시)
        st.metric("데이터 상태", "최신")
    
    st.markdown("---")
    
    # 담당자별 카드 뷰
    st.header("👤 담당자별 리포트")
    
    # 담당자 선택
    user_names = sorted(analyses.keys())
    selected_user = st.selectbox("담당자 선택", [""] + user_names, key="user_select")
    
    if selected_user:
        user_months = analyses[selected_user]
        month_starts = sorted(user_months.keys(), reverse=True)
        
        st.subheader(f"📋 {selected_user} - 월별 분석 리포트")
        
        for month_start in month_starts:
            month_data = user_months[month_start]
            
            # month_start가 date인 경우 문자열로 변환
            if isinstance(month_start, type(today.date())):
                month_display = month_start.strftime("%Y-%m")
            else:
                month_display = str(month_start)
            
            with st.expander(f"📅 {month_data['month_range']} ({month_display})", expanded=True):
                st.markdown("### 🤖 GPT 분석 결과")
                st.markdown(month_data['analysis'])
                
                # 다운로드 버튼
                col1, col2 = st.columns(2)
                with col1:
                    json_data = {
                        "user": selected_user,
                        "month_range": month_data['month_range'],
                        "month_start": month_start.isoformat() if hasattr(month_start, 'isoformat') else str(month_start),
                        "analysis": month_data['analysis']
                    }
                    st.download_button(
                        label="📥 JSON 다운로드",
                        data=json.dumps(json_data, ensure_ascii=False, indent=2),
                        file_name=f"{selected_user}_{month_display}_report.json",
                        mime="application/json"
                    )
                with col2:
                    md_content = f"# {selected_user} - 월별 분석 리포트\n\n"
                    md_content += f"**기간**: {month_data['month_range']}\n\n"
                    md_content += f"**분석일**: {month_display}\n\n---\n\n"
                    md_content += f"## GPT 분석 결과\n\n{month_data['analysis']}"
                    st.download_button(
                        label="📥 Markdown 다운로드",
                        data=md_content,
                        file_name=f"{selected_user}_{month_display}_report.md",
                        mime="text/markdown"
                    )
    else:
        # 담당자 목록 카드 뷰
        st.info("위에서 담당자를 선택하여 상세 리포트를 확인하세요.")
        
        cols = st.columns(3)
        for idx, user_name in enumerate(user_names):
            col_idx = idx % 3
            with cols[col_idx]:
                months_count = len(analyses[user_name])
                st.markdown(f"""
                <div class="metric-container">
                    <h3>👤 {user_name}</h3>
                    <p>분석된 월: <strong>{months_count}개월</strong></p>
                </div>
                """, unsafe_allow_html=True)


def main():
    """메인 함수"""
    if not check_login():
        login_page()
    else:
        main_dashboard()


if __name__ == "__main__":
    main()

