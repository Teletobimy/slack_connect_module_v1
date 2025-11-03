# -*- coding: utf-8 -*-
"""
Slack 채널별 담당자 메시지 분석 및 GPT 기반 업무 리포트 생성기

10월 1일부터 오늘까지의 메시지를 수집하여 담당자별, 주별로 분석하고
GPT를 활용하여 CEO/관리자용 업무 분석 리포트를 생성합니다.
"""

import requests
import os
import sys
import re
import html
import time
import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict
import json

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️ openai 라이브러리가 설치되지 않았습니다. pip install openai를 실행하세요.")

try:
    from supabase import create_client, Client
    from psycopg2 import connect, sql as pg_sql
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("⚠️ supabase 또는 psycopg2 라이브러리가 설치되지 않았습니다.")

# Windows 콘솔 인코딩 문제 해결
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 정규표현식 패턴
MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")
CHANNEL_RE = re.compile(r"<#([CU][A-Z0-9]+)\|([^>]+)>")
URL_RE = re.compile(r"<(https?://[^|>]+)(?:\|[^>]+)?>")


class SlackChannelReporter:
    def __init__(self, user_token: str = None, openai_api_key: str = None, db_connection_string: str = None):
        """
        Slack 채널 리포트 생성기 초기화
        
        Args:
            user_token: Slack User Token (xoxp-로 시작). 환경 변수에서 자동 로드 가능
            openai_api_key: OpenAI API Key. 환경 변수에서 자동 로드 가능
            db_connection_string: Supabase DB 연결 문자열. 환경 변수에서 자동 로드 가능
        """
        self.user_token = user_token or os.getenv("SLACK_USER_TOKEN")
        if not self.user_token:
            raise ValueError("SLACK_USER_TOKEN 환경 변수가 설정되지 않았습니다.")
        
        self.headers = {
            "Authorization": f"Bearer {self.user_token}"
        }
        
        # OpenAI 클라이언트 초기화
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        if self.openai_api_key and OPENAI_AVAILABLE:
            self.client = OpenAI(api_key=self.openai_api_key)
            self.use_gpt = True
        else:
            self.client = None
            self.use_gpt = False
            if not OPENAI_AVAILABLE:
                print("⚠️ OpenAI 라이브러리를 사용할 수 없습니다. GPT 분석이 비활성화됩니다.")
            else:
                print("⚠️ OPENAI_API_KEY가 설정되지 않았습니다. GPT 분석이 비활성화됩니다.")
        
        # Supabase/PostgreSQL 연결 초기화
        self.db_conn_string = db_connection_string or os.getenv("DB_CONNECTION_STRING")
        self.db_conn = None
        if self.db_conn_string and SUPABASE_AVAILABLE:
            try:
                self.db_conn = connect(self.db_conn_string)
                print("✅ Supabase 연결 성공")
            except Exception as e:
                print(f"⚠️ Supabase 연결 실패: {e}")
                self.db_conn = None
        else:
            if not SUPABASE_AVAILABLE:
                print("⚠️ Supabase 라이브러리를 사용할 수 없습니다. DB 저장이 비활성화됩니다.")
            else:
                print("⚠️ DB_CONNECTION_STRING이 설정되지 않았습니다. DB 저장이 비활성화됩니다.")
        
        # 사용자 정보 캐시 (user_id -> 이름)
        self.user_cache = {}
        # user_id -> user_name 매핑 (DB용)
        self.user_id_to_name = {}
    
    def _slack_get(self, url: str, params: Dict[str, Any] = None, max_retries: int = 3) -> Optional[requests.Response]:
        """
        Slack API 호출 공통 함수 (429 레이트 리밋 처리 포함)
        
        Args:
            url: API URL
            params: 요청 파라미터
            max_retries: 최대 재시도 횟수
        
        Returns:
            Response 객체 또는 None
        """
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=self.headers, params=params)
                
                # 429 에러 처리
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        wait_time = int(retry_after)
                    else:
                        # exponential backoff: 2^attempt 초
                        wait_time = 2 ** attempt
                    
                    if attempt < max_retries - 1:
                        print(f"  ⏳ 레이트 리밋 도달, {wait_time}초 대기 중...", end=" ", flush=True)
                        time.sleep(wait_time)
                        continue
                    else:
                        print(f"  ⚠️ 레이트 리밋 재시도 실패 (최대 {max_retries}회)")
                        return None
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  ⚠️ API 호출 오류: {e}")
                    return None
        
        return None
    
    def clean_text(self, text: str) -> str:
        """
        Slack 메시지 텍스트 정규화 (멘션, 채널, URL, HTML 처리)
        
        Args:
            text: 원본 텍스트
        
        Returns:
            정규화된 텍스트
        """
        if not text:
            return ""
        
        # HTML 이스케이프 처리
        text = html.unescape(text)
        
        # 멘션 변환: <@U12345> → @사용자이름
        def replace_mention(match):
            user_id = match.group(1)
            user_name = self.get_user_info(user_id)
            return f"@{user_name}"
        
        text = MENTION_RE.sub(replace_mention, text)
        
        # 채널 변환: <#C12345|channel-name> → #channel-name
        text = CHANNEL_RE.sub(lambda m: f"#{m.group(2)}", text)
        
        # URL 변환: <http://...|text> → http://...
        text = URL_RE.sub(lambda m: m.group(1), text)
        
        return text
    
    def check_existing_week(self, user_id: str, week_start: datetime) -> bool:
        """
        DB에서 특정 사용자의 특정 주차 분석이 이미 존재하는지 확인
        
        Args:
            user_id: Slack 사용자 ID
            week_start: 주 시작일 (월요일)
            
        Returns:
            존재 여부 (True/False)
        """
        if not self.db_conn:
            return False
        
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM metrics_weekly WHERE user_id = %s AND week_start = %s",
                (user_id, week_start.date())
            )
            count = cursor.fetchone()[0]
            cursor.close()
            return count > 0
        except Exception as e:
            print(f"⚠️ DB 조회 오류: {e}")
            return False
    
    def save_message_to_db(self, msg: Dict[str, Any], channel_id: str, channel_type: str):
        """
        메시지를 DB에 저장
        
        Args:
            msg: 메시지 딕셔너리
            channel_id: 채널 ID
            channel_type: 채널 타입
        """
        if not self.db_conn:
            return
        
        try:
            msg_uid = f"{channel_id}_{msg['ts']}"
            ts = float(msg.get("ts", 0))
            thread_ts = float(msg.get("thread_ts", 0)) if msg.get("thread_ts") else None
            user_id = msg.get("user")
            text = msg.get("text", "")
            edited_ts = float(msg.get("edited", {}).get("ts", 0)) if msg.get("edited") else None
            content_hash = hashlib.md5(text.encode()).hexdigest() if text else None
            json_raw = json.dumps(msg, ensure_ascii=False)
            
            cursor = self.db_conn.cursor()
            cursor.execute(
                """INSERT INTO messages (msg_uid, channel_id, thread_ts, ts, user_id, text, edited_ts, content_hash, channel_type, json_raw)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (msg_uid) DO NOTHING""",
                (msg_uid, channel_id, thread_ts, ts, user_id, text, edited_ts, content_hash, channel_type, json_raw)
            )
            self.db_conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️ 메시지 저장 오류: {e}")
            if self.db_conn:
                self.db_conn.rollback()
    
    def save_channel_to_db(self, channel: Dict[str, Any]):
        """
        채널 정보를 DB에 저장
        
        Args:
            channel: 채널 딕셔너리
        """
        if not self.db_conn:
            return
        
        try:
            channel_id = channel.get("id")
            channel_name = channel.get("name", "")
            channel_type = ""
            if channel.get("is_im"):
                channel_type = "im"
            elif channel.get("is_mpim"):
                channel_type = "mpim"
            elif channel.get("is_private"):
                channel_type = "private_channel"
            else:
                channel_type = "public_channel"
            
            is_private = 1 if channel.get("is_private") or channel.get("is_im") or channel.get("is_mpim") else 0
            
            cursor = self.db_conn.cursor()
            cursor.execute(
                """INSERT INTO channels (id, name, type, is_private)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, type = EXCLUDED.type, is_private = EXCLUDED.is_private""",
                (channel_id, channel_name, channel_type, is_private)
            )
            self.db_conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️ 채널 저장 오류: {e}")
            if self.db_conn:
                self.db_conn.rollback()
    
    def save_user_to_db(self, user_id: str, user_data: Dict[str, Any]):
        """
        사용자 정보를 DB에 저장
        
        Args:
            user_id: Slack 사용자 ID
            user_data: 사용자 정보 딕셔너리
        """
        if not self.db_conn:
            return
        
        try:
            real_name = user_data.get("real_name") or user_data.get("name", "")
            name = user_data.get("name", "")
            
            cursor = self.db_conn.cursor()
            cursor.execute(
                """INSERT INTO users (id, real_name, name, updated_at)
                   VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                   ON CONFLICT (id) DO UPDATE SET real_name = EXCLUDED.real_name, name = EXCLUDED.name, updated_at = CURRENT_TIMESTAMP""",
                (user_id, real_name, name)
            )
            self.db_conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️ 사용자 저장 오류: {e}")
            if self.db_conn:
                self.db_conn.rollback()
    
    def save_gpt_analysis_to_db(self, user_id: str, week_start: datetime, week_range: str, analysis_text: str):
        """
        GPT 분석 결과를 DB에 저장
        
        Args:
            user_id: Slack 사용자 ID
            week_start: 주 시작일
            week_range: 주차 범위 문자열
            analysis_text: 분석 결과 텍스트
        """
        if not self.db_conn:
            return
        
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                """INSERT INTO gpt_analyses (user_id, week_start, week_range, analysis_text)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (user_id, week_start) DO UPDATE SET analysis_text = EXCLUDED.analysis_text, created_at = CURRENT_TIMESTAMP""",
                (user_id, week_start.date(), week_range, analysis_text)
            )
            self.db_conn.commit()
            cursor.close()
        except Exception as e:
            print(f"⚠️ GPT 분석 저장 오류: {e}")
            if self.db_conn:
                self.db_conn.rollback()
    
    def get_user_info(self, user_id: str) -> str:
        """
        사용자 ID로부터 사용자 이름 가져오기
        
        Args:
            user_id: Slack 사용자 ID (U로 시작)
        
        Returns:
            사용자 이름 또는 user_id
        """
        if user_id in self.user_cache:
            return self.user_cache[user_id]
        
        response = self._slack_get(
            "https://slack.com/api/users.info",
            params={"user": user_id}
        )
        
        if response:
            data = response.json()
            if data.get("ok"):
                user_data = data.get("user", {})
                user_name = user_data.get("real_name") or user_data.get("name", user_id)
                self.user_cache[user_id] = user_name
                self.user_id_to_name[user_id] = user_name
                
                # DB에 저장
                self.save_user_to_db(user_id, user_data)
                
                return user_name
        
        return user_id
    
    def get_all_channels(self, exclude_archived: bool = True) -> List[Dict[str, Any]]:
        """
        모든 채널 목록 가져오기 (공개 채널, 비공개 채널, DM 포함)
        
        Args:
            exclude_archived: 아카이브된 채널 제외 여부
        
        Returns:
            채널 정보 리스트
        """
        all_channels = []
        
        print("📡 채널 목록 수집 중...")
        
        # 채널 타입: 공개, 비공개, 다중 DM, 1:1 DM
        channel_types_list = [
            ["public_channel"],
            ["private_channel"],
            ["mpim"],  # 다중 DM
            ["im"]     # 1:1 DM
        ]
        
        type_names = {
            "public_channel": "공개 채널",
            "private_channel": "비공개 채널",
            "mpim": "다중 DM",
            "im": "1:1 DM"
        }
        
        for channel_types in channel_types_list:
            cursor = None
            type_name = type_names.get(channel_types[0], channel_types[0])
            
            while True:
                params = {
                    "types": ",".join(channel_types),
                    "limit": 200,
                    "exclude_archived": exclude_archived
                }
                
                if cursor:
                    params["cursor"] = cursor
                
                response = self._slack_get(
                    "https://slack.com/api/conversations.list",
                    params=params
                )
                
                if not response:
                    break
                
                data = response.json()
                
                if not data.get("ok"):
                    error = data.get("error")
                    if error == "missing_scope":
                        if "private_channel" in channel_types:
                            print(f"⚠️ groups:read 권한이 없어 {type_name} 목록을 건너뜁니다.")
                        elif "mpim" in channel_types or "im" in channel_types:
                            print(f"⚠️ im:read, mpim:read 권한이 없어 {type_name} 목록을 건너뜁니다.")
                        else:
                            print(f"❌ {type_name} 목록 조회 오류: {error}")
                            print("💡 channels:read 권한이 필요합니다.")
                    else:
                        print(f"⚠️ {type_name} 목록 조회 오류: {error}")
                    break
                
                channels = data.get("channels", [])
                
                # 보안 관련 채널 제외 (공개/비공개 채널만, DM은 제외하지 않음)
                filtered_channels = []
                for channel in channels:
                    channel_name = channel.get("name", "")
                    
                    # DM인 경우 이름 처리
                    if channel.get("is_im") or channel.get("is_mpim"):
                        # DM 채널의 경우 이름이 없을 수 있음
                        if not channel_name:
                            # 1:1 DM인 경우 상대방 사용자 ID 찾기
                            if channel.get("is_im"):
                                user_id = channel.get("user")
                                if user_id:
                                    channel_name = f"DM: {self.get_user_info(user_id)}"
                                else:
                                    channel_name = "DM: Unknown"
                            else:
                                channel_name = "DM: Group"
                    else:
                        # 공개/비공개 채널만 보안 필터링
                        channel_name_lower = channel_name.lower()
                        if any(keyword in channel_name_lower for keyword in ["security", "보안", "admin", "관리자"]):
                            continue
                    
                    filtered_channels.append(channel)
                
                all_channels.extend(filtered_channels)
                
                cursor = data.get("response_metadata", {}).get("next_cursor")
                if not cursor:
                    break
        
        print(f"✅ 총 {len(all_channels)}개 채널 발견")
        return all_channels
    
    def get_thread_replies(self, channel_id: str, thread_ts: str) -> List[Dict[str, Any]]:
        """
        스레드의 답글 메시지 가져오기
        
        Args:
            channel_id: 채널 ID
            thread_ts: 스레드 타임스탬프
        
        Returns:
            스레드 메시지 리스트
        """
        thread_messages = []
        cursor = None
        
        while True:
            params = {
                "channel": channel_id,
                "ts": thread_ts,
                "limit": 200
            }
            
            if cursor:
                params["cursor"] = cursor
            
            response = self._slack_get(
                "https://slack.com/api/conversations.replies",
                params=params
            )
            
            if not response:
                break
            
            data = response.json()
            
            if not data.get("ok"):
                break
            
            messages = data.get("messages", [])
            
            # 첫 번째 메시지는 원본 메시지이므로 제외
            for msg in messages[1:]:
                if msg.get("subtype"):
                    continue
                if not msg.get("user"):
                    continue
                thread_messages.append(msg)
            
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        
        return thread_messages
    
    def get_period_messages(self, channel_id: str, channel_name: str, start_date: datetime, end_date: datetime) -> List[Dict[str, Any]]:
        """
        특정 채널에서 지정된 기간의 메시지 가져오기 (스레드 포함)
        
        Args:
            channel_id: Slack 채널 ID
            channel_name: 채널 이름 (표시용)
            start_date: 시작 날짜 (datetime 객체)
            end_date: 종료 날짜 (datetime 객체)
        
        Returns:
            메시지 리스트
        """
        # UTC로 변환
        start_ts = int(start_date.astimezone(timezone.utc).timestamp())
        end_ts = int(end_date.astimezone(timezone.utc).timestamp())
        
        all_messages = []
        cursor = None
        
        while True:
            params = {
                "channel": channel_id,
                "oldest": start_ts,
                "latest": end_ts,
                "limit": 200
            }
            
            if cursor:
                params["cursor"] = cursor
            
            response = self._slack_get(
                "https://slack.com/api/conversations.history",
                params=params
            )
            
            if not response:
                break
            
            data = response.json()
            
            if not data.get("ok"):
                error = data.get("error")
                if error in ["channel_not_found", "missing_scope", "not_authed"]:
                    return []
                break
            
            messages = data.get("messages", [])
            
            # 일반 메시지만 필터링
            filtered_messages = []
            for msg in messages:
                if msg.get("subtype"):
                    continue
                if not msg.get("user"):
                    continue
                filtered_messages.append(msg)
                
                # 스레드 메시지 수집
                if msg.get("thread_ts"):
                    thread_replies = self.get_thread_replies(channel_id, msg["thread_ts"])
                    filtered_messages.extend(thread_replies)
            
            all_messages.extend(filtered_messages)
            
            if not data.get("has_more"):
                break
            
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        
        return all_messages
    
    def get_period_range(self) -> tuple:
        """
        분석 기간 계산
        - 첫 실행: 2025-10-20부터 오늘까지
        - 이후 실행: 전주 월요일부터 오늘까지
        
        Returns:
            (start_date, end_date) tuple
        """
        kst = timezone(timedelta(hours=9))
        today = datetime.now(kst)
        first_run_date = datetime(2025, 10, 20, 0, 0, 0, tzinfo=kst)
        
        # 전주 월요일 계산
        days_since_monday = today.weekday()  # 월요일=0
        last_monday = today - timedelta(days=days_since_monday + 7)  # 전주 월요일
        
        # 첫 실행인지 확인 (DB에 데이터가 있는지)
        has_previous_data = False
        if self.db_conn:
            try:
                cursor = self.db_conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM messages LIMIT 1")
                has_previous_data = cursor.fetchone()[0] > 0
                cursor.close()
            except:
                pass
        
        if has_previous_data:
            start_date = last_monday.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start_date = first_run_date
        
        end_date = today
        return (start_date, end_date)
    
    def get_week_start_date(self, date: datetime) -> datetime:
        """
        주어진 날짜가 속한 주의 월요일 반환
        
        Args:
            date: datetime 객체
            
        Returns:
            해당 주의 월요일 datetime 객체
        """
        days_since_monday = date.weekday()  # 월요일=0
        monday = date - timedelta(days=days_since_monday)
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    
    def get_week_number(self, date: datetime) -> int:
        """날짜로부터 주 번호 계산 (10월 20일을 1주차로 시작)"""
        kst = timezone(timedelta(hours=9))
        base_date = datetime(2025, 10, 20, tzinfo=kst)
        base_monday = self.get_week_start_date(base_date)
        target_monday = self.get_week_start_date(date)
        days_diff = (target_monday.date() - base_monday.date()).days
        return (days_diff // 7) + 1
    
    def analyze_user_work_with_gpt(self, user_name: str, week_range: str, messages: List[Dict[str, Any]]) -> Optional[str]:
        """
        GPT를 사용하여 담당자의 주별 업무를 분석
        
        Args:
            user_name: 담당자 이름
            week_range: 주차 범위 문자열 (예: "10/01~10/07")
            messages: 해당 주의 메시지 리스트 (clean_text가 적용된 텍스트 포함)
        
        Returns:
            분석 결과 텍스트 또는 None
        """
        if not self.use_gpt or not self.client:
            return None
        
        if not messages:
            return None
        
        # 최신 30개만 선택 (이미 클린된 텍스트)
        samples = sorted(messages, key=lambda m: m["datetime"])[-30:]
        sample_lines = []
        
        for m in samples:
            date_str = m["datetime"].strftime("%Y-%m-%d %H:%M")
            text = m["text"][:400]  # 최대 400자
            channel = m.get("channel", "unknown")
            sample_lines.append(f"[{date_str} | #{channel}] {text}")
        
        messages_str = "\n".join(sample_lines)
        
        prompt = f"""
당신은 CEO/임원에게 보고하는 '업무 퍼포먼스 코치'입니다.

[대상] {user_name}
[기간] {week_range}

[메시지 샘플(최신 30)]
{messages_str}

위 메시지들을 분석하여 다음 정보를 파악하고 보고하세요:

1) 주요 업무 및 성과 요약(불릿 3~6개)
   - 메시지 내용을 바탕으로 담당자의 주요 업무와 성과를 요약
   - 정량 지표: 총 메시지 수, 활성일 수, 평균 메시지 간격, 최대 공백 시간
   - 완료 신호 수(완료, 완료됨, 끝남, 마무리 등 키워드 기반)
   - 블로커 신호 수(막힘, 문제, 지연, 어려움, 도와주세요 등 키워드 기반)
   - 체크리스트 진행률([x], [o], [-], 완료 표시 등)
   - 협업성(멘션 수, @사용자 언급 횟수)
   - 상위 활동 채널 및 커버리지

2) 진행속도/진행률 판단(근거 포함)
   - 업무 진행 속도 평가 (빠름/보통/느림)
   - 구체적 근거 제시

3) 리스크/블로커와 해결책(불릿)
   - 발견된 리스크나 블로커 요약
   - 각각에 대한 해결 방안 제시

4) Business 조언(우선순위 재정렬, 협업설계, 리소스/승인 필요) - 3~5개
   - 경영진이 고려해야 할 업무 조정 사항
   - 협업 개선 방안
   - 필요한 리소스나 승인 사항

5) Personal 코칭(커뮤니케이션 습관, 집중·체력·정서관리 팁) - 3~5개
   - 개인 성장을 위한 코칭 포인트
   - 커뮤니케이션 스타일 개선
   - 워크라이프 밸런스 관련 조언

6) 다음 주 KPI 제안(정량 목표 3개: 예, 완료신호≥X, 블로커신호≤Y, 체크리스트 진행률≥Z%)
   - 측정 가능한 목표 설정
   - 구체적인 수치 제시

각 섹션을 명확히 구분하여 작성하고, 한국어로 작성하세요.
"""
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "당신은 데이터에 근거한 임원 보고 코치입니다. 단정적·실용적으로 제안하세요."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.4,
                max_tokens=1200
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"  ⚠️ GPT 분석 오류 ({user_name} {week_range}): {e}")
            return None
    
    def generate_weekly_analysis_report(self):
        """
        10월 1일부터 오늘까지의 메시지를 수집하고 주별로 분석하여
        CEO/관리자용 업무 분석 리포트 생성
        """
        print("=" * 80)
        print("📊 Slack 담당자별 주간 업무 분석 리포트 (CEO/관리자용)")
        print("=" * 80)
        print()
        
        # 기간 설정 (10/20부터 또는 전주 월요일부터)
        start_date, end_date = self.get_period_range()
        
        print(f"📅 조회 기간: {start_date.strftime('%Y년 %m월 %d일')} ~ {end_date.strftime('%Y년 %m월 %d일')}")
        print()
        
        # 모든 채널 가져오기
        channels = self.get_all_channels(exclude_archived=True)
        
        if not channels:
            print("❌ 수집할 채널이 없습니다.")
            return
        
        print()
        print("=" * 80)
        print("📝 채널별 메시지 수집 시작...")
        print("=" * 80)
        print()
        
        # 담당자별, 주별 메시지 저장
        # 구조: {user_name: {week_num: [{text, timestamp, channel, date, datetime}]}}
        user_weekly_messages = defaultdict(lambda: defaultdict(list))
        
        # 각 채널에서 메시지 수집
        total_channels = len(channels)
        for idx, channel in enumerate(channels, 1):
            channel_id = channel.get("id")
            
            # 채널 이름 결정
            if channel.get("is_im"):
                user_id = channel.get("user")
                if user_id:
                    channel_name = f"DM: {self.get_user_info(user_id)}"
                else:
                    channel_name = "DM: Unknown"
            elif channel.get("is_mpim"):
                channel_name = "DM: Group"
            else:
                channel_name = channel.get("name", "Unknown")
            
            is_private = channel.get("is_private", False)
            is_dm = channel.get("is_im") or channel.get("is_mpim")
            
            channel_type = "💬" if is_dm else ("🔒" if is_private else "#")
            print(f"[{idx}/{total_channels}] {channel_type}{channel_name} 처리 중...", end=" ", flush=True)
            
            # 채널 정보 DB에 저장
            self.save_channel_to_db(channel)
            
            messages = self.get_period_messages(channel_id, channel_name, start_date, end_date)
            
            if messages:
                print(f"✅ {len(messages)}개 메시지 발견")
                
                # 채널 타입 결정 (DB 저장용)
                db_channel_type = ""
                if channel.get("is_im"):
                    db_channel_type = "im"
                elif channel.get("is_mpim"):
                    db_channel_type = "mpim"
                elif channel.get("is_private"):
                    db_channel_type = "private_channel"
                else:
                    db_channel_type = "public_channel"
                
                # 담당자별, 주별로 그룹화 및 DB 저장
                kst = timezone(timedelta(hours=9))
                for msg in messages:
                    user_id = msg.get("user")
                    if user_id:
                        # DB에 메시지 저장
                        self.save_message_to_db(msg, channel_id, db_channel_type)
                        
                        user_name = self.get_user_info(user_id)
                        # clean_text 적용
                        text = self.clean_text(msg.get("text", ""))
                        ts = float(msg.get("ts", 0))
                        msg_time = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(kst)
                        week_num = self.get_week_number(msg_time)
                        
                        user_weekly_messages[user_name][week_num].append({
                            "text": text,
                            "timestamp": ts,
                            "channel": channel_name,
                            "date": msg_time.date(),
                            "datetime": msg_time,
                            "user_id": user_id  # DB 조회용
                        })
            else:
                print("메시지 없음")
        
        print()
        print("=" * 80)
        print("📊 메시지 수집 완료, GPT 분석 시작...")
        print("=" * 80)
        print()
        
        # 담당자별, 주별 GPT 분석 수행
        user_weekly_analysis = defaultdict(dict)
        
        total_users = len(user_weekly_messages)
        user_idx = 0
        
        for user_name, weekly_data in sorted(user_weekly_messages.items()):
            user_idx += 1
            total_weeks = len(weekly_data)
            week_idx = 0
            
            print(f"[{user_idx}/{total_users}] 👤 {user_name} 분석 중...")
            
            kst = timezone(timedelta(hours=9))
            for week_num in sorted(weekly_data.keys()):
                week_idx += 1
                messages = weekly_data[week_num]
                
                # 주차 범위 계산 (10/20 기준)
                base_date = datetime(2025, 10, 20, tzinfo=kst)
                base_monday = self.get_week_start_date(base_date)
                week_start = base_monday + timedelta(days=(week_num-1)*7)
                week_end = min(week_start + timedelta(days=6), end_date)
                week_range = f"{week_start.strftime('%m/%d')}~{week_end.strftime('%m/%d')}"
                
                # 사용자 ID 찾기 (첫 메시지에서)
                user_id = None
                if messages:
                    user_id = messages[0].get("user_id")
                
                # 중복 체크
                if user_id and self.check_existing_week(user_id, week_start):
                    print(f"  → {week_num}주차 ({week_range}, {len(messages)}개 메시지) 이미 분석됨 ⏭️")
                    continue
                
                print(f"  → {week_num}주차 ({week_range}, {len(messages)}개 메시지) 분석 중...", end=" ", flush=True)
                
                analysis = self.analyze_user_work_with_gpt(user_name, week_range, messages)
                
                if analysis:
                    user_weekly_analysis[user_name][week_num] = {
                        "analysis": analysis,
                        "message_count": len(messages),
                        "messages": messages,
                        "week_range": week_range,
                        "week_start": week_start
                    }
                    
                    # DB에 GPT 분석 결과 저장
                    if user_id:
                        self.save_gpt_analysis_to_db(user_id, week_start, week_range, analysis)
                    
                    print("✅")
                else:
                    print("⏭️")
        
        print()
        print("=" * 80)
        print("📋 CEO/관리자용 주간 업무 분석 리포트")
        print("=" * 80)
        print()
        
        # 담당자별 리포트 출력
        for user_name in sorted(user_weekly_analysis.keys()):
            print("\n" + "=" * 80)
            print(f"👤 담당자: {user_name}")
            print("=" * 80)
            
            for week_num in sorted(user_weekly_analysis[user_name].keys()):
                data = user_weekly_analysis[user_name][week_num]
                
                print(f"\n📅 {week_num}주차 ({data['week_range']})")
                print(f"   총 {data['message_count']}개 메시지")
                print("-" * 80)
                
                # 주요 채널 및 활동 요약
                channels_summary = defaultdict(int)
                for msg in data["messages"][:20]:  # 최근 20개만
                    channels_summary[msg["channel"]] += 1
                
                if channels_summary:
                    print("   주요 활동 채널:")
                    for ch, count in sorted(channels_summary.items(), key=lambda x: x[1], reverse=True)[:5]:
                        print(f"     - {ch}: {count}건")
                
                print()
                print("🤖 GPT 분석 결과:")
                print("-" * 80)
                print(data["analysis"])
                print()
        
        # 전체 요약 통계
        print()
        print("=" * 80)
        print("📊 전체 요약 통계")
        print("=" * 80)
        
        total_messages = sum(
            sum(data["message_count"] for data in user_data.values())
            for user_data in user_weekly_analysis.values()
        )
        
        print(f"분석된 담당자 수: {len(user_weekly_analysis)}명")
        print(f"총 메시지 수: {total_messages}개")
        print(f"분석 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
        
        print()
        print("=" * 80)
        print("✅ 리포트 생성 완료")
        print("=" * 80)


def main():
    """메인 함수"""
    try:
        # 환경 변수에서 토큰 로드
        user_token = os.getenv("SLACK_USER_TOKEN")
        openai_api_key = os.getenv("OPENAI_API_KEY")
        
        if not user_token:
            print("❌ SLACK_USER_TOKEN 환경 변수가 설정되지 않았습니다.")
            print("\n설정 방법:")
            print("1. Windows PowerShell:")
            print('   $env:SLACK_USER_TOKEN="xoxp-your-token"')
            return
        
        if not openai_api_key:
            print("⚠️ OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
            print("GPT 분석 없이 진행합니다.")
            print("\n설정 방법:")
            print('   $env:OPENAI_API_KEY="sk-your-api-key"')
        
        # 리포트 생성
        reporter = SlackChannelReporter(user_token=user_token, openai_api_key=openai_api_key)
        reporter.generate_weekly_analysis_report()
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
