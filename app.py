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
    try:
        user_token = st.secrets.get("SLACK_USER_TOKEN")
        openai_api_key = st.secrets.get("OPENAI_API_KEY")
        db_connection_string = st.secrets.get("DB_CONNECTION_STRING")
        
        if not user_token:
            st.error("❌ SLACK_USER_TOKEN이 설정되지 않았습니다.")
            return None
        
        return SlackChannelReporter(
            user_token=user_token,
            openai_api_key=openai_api_key,
            db_connection_string=db_connection_string
        )
    except Exception as e:
        st.error(f"❌ 리포터 초기화 오류: {e}")
        return None


def load_analyses_from_db(reporter: SlackChannelReporter) -> Dict[str, Dict]:
    """DB에서 분석 결과 로드"""
    if not reporter or not reporter.db_conn:
        return {}
    
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
            user_id, user_name, week_start, week_range, analysis_text = row
            user_name = user_name or user_id
            
            if user_name not in results:
                results[user_name] = {}
            
            results[user_name][week_start] = {
                "week_range": week_range,
                "analysis": analysis_text,
                "week_start": week_start
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
                    if reporter.db_conn:
                        st.success(f"✅ 연결 성공: {reporter.db_connection_status}")
                        if reporter.db_connection_type:
                            st.info(f"연결 타입: {reporter.db_connection_type}")
                        
                        # 테이블 존재 여부 확인
                        try:
                            cursor = reporter.db_conn.cursor()
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
                        st.error(f"❌ 연결 실패: {reporter.db_connection_status}")
                
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
                
                # 콜백 함수 설정
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
                            
                            # DB 통계 표시
                            st.markdown("---")
                            st.subheader("📊 DB 저장 통계")
                            col1, col2 = st.columns(2)
                            with col1:
                                st.metric("메시지 저장", f"{reporter.db_stats['messages_saved']}개", 
                                         delta=f"-{reporter.db_stats['messages_failed']}개 실패" if reporter.db_stats['messages_failed'] > 0 else None)
                                st.metric("채널 저장", f"{reporter.db_stats['channels_saved']}개",
                                         delta=f"-{reporter.db_stats['channels_failed']}개 실패" if reporter.db_stats['channels_failed'] > 0 else None)
                            with col2:
                                st.metric("사용자 저장", f"{reporter.db_stats['users_saved']}개",
                                         delta=f"-{reporter.db_stats['users_failed']}개 실패" if reporter.db_stats['users_failed'] > 0 else None)
                                st.metric("GPT 분석 저장", f"{reporter.db_stats['analyses_saved']}개",
                                         delta=f"-{reporter.db_stats['analyses_failed']}개 실패" if reporter.db_stats['analyses_failed'] > 0 else None)
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
    total_weeks = sum(len(weeks) for weeks in analyses.values())
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("분석된 담당자 수", f"{total_users}명")
    with col2:
        st.metric("총 주차 수", f"{total_weeks}주")
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
        user_weeks = analyses[selected_user]
        week_starts = sorted(user_weeks.keys(), reverse=True)
        
        st.subheader(f"📋 {selected_user} - 주간 분석 리포트")
        
        for week_start in week_starts:
            week_data = user_weeks[week_start]
            
            with st.expander(f"📅 {week_data['week_range']} ({week_start})", expanded=True):
                st.markdown("### 🤖 GPT 분석 결과")
                st.markdown(week_data['analysis'])
                
                # 다운로드 버튼
                col1, col2 = st.columns(2)
                with col1:
                    json_data = {
                        "user": selected_user,
                        "week_range": week_data['week_range'],
                        "week_start": week_start.isoformat(),
                        "analysis": week_data['analysis']
                    }
                    st.download_button(
                        label="📥 JSON 다운로드",
                        data=json.dumps(json_data, ensure_ascii=False, indent=2),
                        file_name=f"{selected_user}_{week_start}_report.json",
                        mime="application/json"
                    )
                with col2:
                    md_content = f"# {selected_user} - 주간 분석 리포트\n\n"
                    md_content += f"**기간**: {week_data['week_range']}\n\n"
                    md_content += f"**분석일**: {week_start}\n\n---\n\n"
                    md_content += f"## GPT 분석 결과\n\n{week_data['analysis']}"
                    st.download_button(
                        label="📥 Markdown 다운로드",
                        data=md_content,
                        file_name=f"{selected_user}_{week_start}_report.md",
                        mime="text/markdown"
                    )
    else:
        # 담당자 목록 카드 뷰
        st.info("위에서 담당자를 선택하여 상세 리포트를 확인하세요.")
        
        cols = st.columns(3)
        for idx, user_name in enumerate(user_names):
            col_idx = idx % 3
            with cols[col_idx]:
                weeks_count = len(analyses[user_name])
                st.markdown(f"""
                <div class="metric-container">
                    <h3>👤 {user_name}</h3>
                    <p>분석된 주차: <strong>{weeks_count}주</strong></p>
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

