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
import io
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from collections import defaultdict
import json

# Windows 콘솔 인코딩 문제 해결 (가장 먼저 실행)
if sys.platform == "win32":
    # 이미 설정되어 있지 않은 경우에만 설정
    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        except (AttributeError, ValueError):
            # 이미 닫혔거나 재설정할 수 없는 경우 무시
            pass

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

# 정규표현식 패턴
MENTION_RE = re.compile(r"<@([UW][A-Z0-9]+)>")
CHANNEL_RE = re.compile(r"<#([CU][A-Z0-9]+)\|([^>]+)>")
URL_RE = re.compile(r"<(https?://[^|>]+)(?:\|[^>]+)?>")


class SlackChannelReporter:
    def __getattr__(self, name):
        """속성이 없을 때 호출되는 메서드 - 안전성 강화"""
        # log_callback과 progress_callback은 반드시 None 반환
        if name in ['log_callback', 'progress_callback']:
            print(f"[WARNING] {name}이 없어서 None 반환 (이것은 비정상적입니다!)")
            print(f"[WARNING] 현재 객체 속성: {[x for x in dir(self) if not x.startswith('_')]}")
            return None
        # 다른 속성은 일반적인 AttributeError
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
    
    def __init__(self, user_token: str = None, openai_api_key: str = None, db_connection_string: str = None):
        """
        Slack 채널 리포트 생성기 초기화
        
        Args:
            user_token: Slack User Token (xoxp-로 시작). 환경 변수에서 자동 로드 가능
            openai_api_key: OpenAI API Key. 환경 변수에서 자동 로드 가능
            db_connection_string: Supabase DB 연결 문자열. 환경 변수에서 자동 로드 가능
        """
        import traceback
        
        # ⚠️ 필수 속성 먼저 초기화 (예외 발생 시에도 보장)
        # 이 속성들은 반드시 존재해야 하므로 try 블록 밖에서 초기화
        self.progress_callback = None
        self.log_callback = None
        self.user_token = None
        self.headers = {}
        self.client = None
        self.use_gpt = False
        self.openai_api_key = None
        self.user_cache = {}
        self.user_id_to_name = {}
        self.db_stats = {
            'messages_saved': 0,
            'messages_failed': 0,
            'channels_saved': 0,
            'channels_failed': 0,
            'users_saved': 0,
            'users_failed': 0,
            'analyses_saved': 0,
            'analyses_failed': 0
        }
        self.db_conn_string = None
        self.db_conn = None
        self.db_connection_status = "미연결"
        self.db_connection_type = None
        
        print(f"[DEBUG] __init__ 필수 속성 사전 초기화 완료")
        print(f"[DEBUG] hasattr(log_callback)={hasattr(self, 'log_callback')}")
        print(f"[DEBUG] hasattr(progress_callback)={hasattr(self, 'progress_callback')}")
        
        # 강제로 속성 존재 확인 및 검증
        assert hasattr(self, 'log_callback'), "log_callback이 초기화되지 않았습니다!"
        assert hasattr(self, 'progress_callback'), "progress_callback이 초기화되지 않았습니다!"
        print(f"[DEBUG] 속성 검증 통과: log_callback={type(self.log_callback)}, progress_callback={type(self.progress_callback)}")
        
        try:
            # Step 1: 콜백 함수들 (이미 초기화됨, 확인만)
            print(f"[DEBUG] __init__ Step 1: 콜백 함수 확인")
            print(f"[DEBUG] __init__ Step 1: log_callback={self.log_callback}, progress_callback={self.progress_callback}")
            
            # Step 2: User token 초기화
            print(f"[DEBUG] __init__ Step 2: User token 초기화 시작")
            self.user_token = user_token or os.getenv("SLACK_USER_TOKEN")
            if not self.user_token:
                raise ValueError("SLACK_USER_TOKEN 환경 변수가 설정되지 않았습니다.")
            
            self.headers = {
                "Authorization": f"Bearer {self.user_token}"
            }
            
            # OpenAI 클라이언트 초기화
            print(f"[DEBUG] __init__ Step 3: OpenAI 클라이언트 초기화 시작")
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
            
            # Step 4: 캐시 및 통계 (이미 초기화됨, 확인만)
            print(f"[DEBUG] __init__ Step 4: 캐시 및 통계 확인")
            
            # Step 5: Supabase/PostgreSQL 연결 초기화
            print(f"[DEBUG] __init__ Step 5: Supabase 연결 초기화 시작")
            self.db_conn_string = db_connection_string or os.getenv("DB_CONNECTION_STRING")
            
            if self.db_conn_string and SUPABASE_AVAILABLE:
                # 디버그: _log 호출 전 확인
                print(f"[DEBUG] DB 연결 시작 전: hasattr(log_callback)={hasattr(self, 'log_callback')}")
                print(f"[DEBUG] DB 연결 시작 전: log_callback 값={getattr(self, 'log_callback', 'NOT_EXISTS')}")
                try:
                    self._log("🔌 Supabase 연결 시도 중...")
                    self._log(f"   연결 문자열: {self.db_conn_string[:60]}...")
                except AttributeError as log_err:
                    print(f"[DEBUG] ❌ _log 호출 시 AttributeError 발생: {log_err}")
                    print(f"[DEBUG] 현재 객체 속성: {dir(self)}")
                    raise
                # Direct connection 시도
                try:
                    self.db_conn = connect(self.db_conn_string)
                    # 연결 테스트
                    cursor = self.db_conn.cursor()
                    cursor.execute("SELECT version();")
                    version = cursor.fetchone()[0]
                    cursor.close()
                    self.db_connection_status = "연결 성공"
                    self.db_connection_type = "Direct (포트 5432)"
                    self._log("✅ Supabase 연결 성공 (Direct connection)")
                    self._log(f"   PostgreSQL 버전: {version.split(',')[0]}")
                    
                    # 테이블 자동 생성 확인 및 실행
                    self._ensure_tables_exist()
                except Exception as e:
                    error_msg = str(e).lower()
                    # IPv4/DNS 문제인 경우 Session Pooler로 재시도
                    if "could not translate host name" in error_msg or "name or service not known" in error_msg:
                        self._log(f"⚠️ Direct connection 실패 (IPv4/DNS 문제): {e}")
                        self._log("🔄 Session Pooler로 재시도 중...")
                        
                        # Session Pooler 연결 문자열 생성 (포트 6543)
                        pooler_string = None
                        if ":5432/" in self.db_conn_string:
                            pooler_string = self.db_conn_string.replace(":5432/", ":6543/postgres")
                        elif ":5432" in self.db_conn_string:
                            pooler_string = self.db_conn_string.replace(":5432", ":6543")
                        
                        if pooler_string:
                            try:
                                self.db_conn = connect(pooler_string)
                                # 연결 테스트
                                cursor = self.db_conn.cursor()
                                cursor.execute("SELECT version();")
                                version = cursor.fetchone()[0]
                                cursor.close()
                                self.db_connection_status = "연결 성공"
                                self.db_connection_type = "Session Pooler (포트 6543)"
                                self._log("✅ Supabase 연결 성공 (Session Pooler)")
                                self._log(f"   PostgreSQL 버전: {version.split(',')[0]}")
                                self.db_conn_string = pooler_string  # 나중에 사용하기 위해 저장
                                
                                # 테이블 자동 생성 확인 및 실행
                                self._ensure_tables_exist()
                            except Exception as e2:
                                self.db_connection_status = f"연결 실패: {str(e2)[:100]}"
                                self._log(f"❌ Session Pooler 연결도 실패: {e2}")
                                self._log("💡 Supabase 대시보드에서 Session Pooler 연결 문자열을 직접 확인하세요.")
                                self.db_conn = None
                        else:
                            self.db_connection_status = "Session Pooler 문자열 생성 실패"
                            self._log("💡 Session Pooler 연결 문자열을 수동으로 설정하세요:")
                            self._log("   포트를 6543으로 변경: postgresql://...@host:6543/postgres")
                            self.db_conn = None
                    else:
                        self.db_connection_status = f"연결 실패: {str(e)[:100]}"
                        self._log(f"❌ Supabase 연결 실패: {e}")
                        self.db_conn = None
            else:
                if not SUPABASE_AVAILABLE:
                    self.db_connection_status = "라이브러리 없음"
                    print(f"[DEBUG] SUPABASE_AVAILABLE=False, _log 호출 전")
                    print(f"[DEBUG] hasattr(log_callback)={hasattr(self, 'log_callback')}")
                    try:
                        self._log("⚠️ Supabase 라이브러리를 사용할 수 없습니다. DB 저장이 비활성화됩니다.")
                    except AttributeError as log_err:
                        print(f"[DEBUG] ❌ _log 호출 시 AttributeError: {log_err}")
                        print(f"[DEBUG] 현재 객체 속성: {dir(self)}")
                        raise
                else:
                    self.db_connection_status = "연결 문자열 없음"
                    print(f"[DEBUG] DB_CONNECTION_STRING 없음, _log 호출 전")
                    print(f"[DEBUG] hasattr(log_callback)={hasattr(self, 'log_callback')}")
                    try:
                        self._log("⚠️ DB_CONNECTION_STRING이 설정되지 않았습니다. DB 저장이 비활성화됩니다.")
                    except AttributeError as log_err:
                        print(f"[DEBUG] ❌ _log 호출 시 AttributeError: {log_err}")
                        print(f"[DEBUG] 현재 객체 속성: {dir(self)}")
                        raise
            
            print(f"[DEBUG] __init__ 완료!")
        
        except AttributeError as attr_err:
            print(f"[DEBUG] ❌ __init__ 중 AttributeError 발생: {attr_err}")
            print(f"[DEBUG] 현재 객체 속성 목록: {dir(self)}")
            print(f"[DEBUG] 전체 스택 트레이스:")
            import traceback
            traceback.print_exc()
            raise
        except Exception as init_err:
            print(f"[DEBUG] ❌ __init__ 중 예외 발생: {init_err}")
            print(f"[DEBUG] 오류 타입: {type(init_err).__name__}")
            import traceback
            traceback.print_exc()
            raise
    
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
    
    def check_existing_month(self, user_id: str, month_start: datetime) -> bool:
        """
        DB에서 특정 사용자의 특정 월 분석이 이미 존재하는지 확인 (gpt_analyses 테이블 기준)
        
        Args:
            user_id: Slack 사용자 ID
            month_start: 월 시작일 (1일)
            
        Returns:
            존재 여부 (True/False)
        """
        if not self.db_conn:
            return False
        
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM gpt_analyses WHERE user_id = %s AND week_start = %s",
                (user_id, month_start.date())
            )
            count = cursor.fetchone()[0]
            cursor.close()
            return count > 0
        except Exception as e:
            self._log(f"⚠️ [DB] 월별 확인 조회 오류: {str(e)[:200]}")
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
            return False
        
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
            rows_inserted = cursor.rowcount
            self.db_conn.commit()
            cursor.close()
            
            if rows_inserted > 0:
                self.db_stats['messages_saved'] += 1
            return True
        except Exception as e:
            self.db_stats['messages_failed'] += 1
            self._log(f"⚠️ [DB] 메시지 저장 오류 ({msg_uid[:30]}...): {str(e)[:200]}")
            if self.db_conn:
                self.db_conn.rollback()
            return False
    
    def save_channel_to_db(self, channel: Dict[str, Any]):
        """
        채널 정보를 DB에 저장
        
        Args:
            channel: 채널 딕셔너리
        """
        if not self.db_conn:
            return False
        
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
            self.db_stats['channels_saved'] += 1
            return True
        except Exception as e:
            self.db_stats['channels_failed'] += 1
            self._log(f"⚠️ [DB] 채널 저장 오류 ({channel_id}): {str(e)[:200]}")
            if self.db_conn:
                self.db_conn.rollback()
            return False
    
    def save_user_to_db(self, user_id: str, user_data: Dict[str, Any]):
        """
        사용자 정보를 DB에 저장
        
        Args:
            user_id: Slack 사용자 ID
            user_data: 사용자 정보 딕셔너리
        """
        if not self.db_conn:
            return False
        
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
            self.db_stats['users_saved'] += 1
            return True
        except Exception as e:
            self.db_stats['users_failed'] += 1
            self._log(f"⚠️ [DB] 사용자 저장 오류 ({user_id}): {str(e)[:200]}")
            if self.db_conn:
                self.db_conn.rollback()
            return False
    
    def save_gpt_analysis_to_db(self, user_id: str, month_start: datetime, month_range: str, analysis_text: str):
        """
        GPT 분석 결과를 DB에 저장
        
        Args:
            user_id: Slack 사용자 ID
            month_start: 월 시작일
            month_range: 월 범위 문자열
            analysis_text: 분석 결과 텍스트
        """
        if not self.db_conn:
            self._log("⚠️ [DB] GPT 분석 저장 실패: DB 연결 없음")
            return False
        
        try:
            cursor = self.db_conn.cursor()
            cursor.execute(
                """INSERT INTO gpt_analyses (user_id, week_start, week_range, analysis_text)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (user_id, week_start) DO UPDATE SET analysis_text = EXCLUDED.analysis_text, created_at = CURRENT_TIMESTAMP""",
                (user_id, month_start.date(), month_range, analysis_text)
            )
            self.db_conn.commit()
            cursor.close()
            self.db_stats['analyses_saved'] += 1
            self._log(f"✅ [DB] GPT 분석 저장 성공: user_id={user_id}, month={month_range}")
            return True
        except Exception as e:
            self.db_stats['analyses_failed'] += 1
            self._log(f"❌ [DB] GPT 분석 저장 오류 (user_id={user_id}, month={month_range}): {str(e)[:200]}")
            if self.db_conn:
                self.db_conn.rollback()
            return False
    
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
        
        self._log("📡 채널 목록 수집 중...")
        
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
                            self._log(f"⚠️ groups:read 권한이 없어 {type_name} 목록을 건너뜁니다.")
                        elif "mpim" in channel_types or "im" in channel_types:
                            self._log(f"⚠️ im:read, mpim:read 권한이 없어 {type_name} 목록을 건너뜁니다.")
                        else:
                            self._log(f"❌ {type_name} 목록 조회 오류: {error}")
                            self._log("💡 channels:read 권한이 필요합니다.")
                    else:
                        self._log(f"⚠️ {type_name} 목록 조회 오류: {error}")
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
        
        self._log(f"✅ 총 {len(all_channels)}개 채널 발견")
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
        - 첫 실행: 2025-09-01부터 오늘까지
        - 이후 실행: 전월 1일부터 오늘까지
        
        Returns:
            (start_date, end_date) tuple
        """
        kst = timezone(timedelta(hours=9))
        today = datetime.now(kst)
        first_run_date = datetime(2025, 9, 1, 0, 0, 0, tzinfo=kst)
        
        # 전월 1일 계산
        if today.month == 1:
            last_month = 12
            last_year = today.year - 1
        else:
            last_month = today.month - 1
            last_year = today.year
        last_month_start = datetime(last_year, last_month, 1, 0, 0, 0, tzinfo=kst)
        
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
            start_date = last_month_start
        else:
            start_date = first_run_date
        
        end_date = today
        return (start_date, end_date)
    
    def get_month_start_date(self, date: datetime) -> datetime:
        """
        주어진 날짜가 속한 월의 1일 반환
        
        Args:
            date: datetime 객체
            
        Returns:
            해당 월의 1일 datetime 객체
        """
        return date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    
    def get_month_key(self, date: datetime) -> str:
        """날짜로부터 월 키 계산 (예: "2025-09")"""
        return date.strftime("%Y-%m")
    
    def analyze_user_work_with_gpt(self, user_name: str, month_range: str, messages: List[Dict[str, Any]]) -> Optional[str]:
        """
        GPT를 사용하여 담당자의 월별 업무를 분석
        
        Args:
            user_name: 담당자 이름
            month_range: 월 범위 문자열 (예: "2025년 9월")
            messages: 해당 월의 메시지 리스트 (clean_text가 적용된 텍스트 포함)
        
        Returns:
            분석 결과 텍스트 또는 None
        """
        if not self.use_gpt or not self.client:
            return None
        
        if not messages:
            return None
        
        # 전체 메시지 사용 (월별 분석이므로 전체 메시지 사용)
        # 날짜순으로 정렬
        sorted_messages = sorted(messages, key=lambda m: m["datetime"])
        sample_lines = []
        
        for m in sorted_messages:
            date_str = m["datetime"].strftime("%Y-%m-%d %H:%M")
            text = m["text"][:400]  # 최대 400자
            channel = m.get("channel", "unknown")
            sample_lines.append(f"[{date_str} | #{channel}] {text}")
        
        messages_str = "\n".join(sample_lines)
        
        prompt = f"""
당신은 CEO/임원에게 보고하는 '업무 퍼포먼스 코치'입니다.

[대상] {user_name}
[기간] {month_range}

[전체 메시지 ({len(sorted_messages)}개)]
{messages_str}

위 메시지들을 분석하여 다음 정보를 파악하고 보고하세요:

1) 주요 업무 (명시적으로 작성, 불릿 3~6개)
   - 메시지 내용을 바탕으로 담당자가 실제로 수행한 구체적인 업무를 명시적으로 나열
   - 각 업무 항목은 무엇을 했는지가 명확히 드러나도록 작성
   - 예: "프로젝트 X의 API 설계 및 구현 완료", "클라이언트 Y와의 미팅 및 요구사항 정리" 등
   - 정량 지표: 총 메시지 수, 활성일 수, 평균 메시지 간격, 최대 공백 시간
   - 협업성(멘션 수, @사용자 언급 횟수)
   - 상위 활동 채널 및 커버리지

2) Business 조언(우선순위 재정렬, 협업설계, 리소스/승인 필요) - 3~5개
   - 경영진이 고려해야 할 업무 조정 사항
   - 협업 개선 방안
   - 필요한 리소스나 승인 사항

3) Personal 코칭(커뮤니케이션 습관, 집중·체력·정서관리 팁) - 3~5개
   - 개인 성장을 위한 코칭 포인트
   - 커뮤니케이션 스타일 개선
   - 워크라이프 밸런스 관련 조언

4) 다음 달 KPI 제안(정량 목표 3개)
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
            print(f"  ⚠️ GPT 분석 오류 ({user_name} {month_range}): {e}")
            return None
    
    def _log(self, message: str):
        """로그 출력 (Streamlit 또는 print) - 완전히 안전한 버전"""
        # 가장 안전한 방법: getattr 사용
        try:
            log_callback = getattr(self, 'log_callback', None)
            if log_callback is not None:
                try:
                    log_callback(message)
                    return
                except Exception as e:
                    # 콜백 호출 실패 시 print로 대체
                    print(f"[콜백 오류] {message}")
                    print(f"  오류: {e}")
                    return
        except Exception as getattr_err:
            # getattr 자체가 실패한 경우 (매우 드묾)
            print(f"[DEBUG _log] ⚠️ getattr 실패: {getattr_err}")
        
        # 기본: print로 출력
        print(message)
    
    def _ensure_tables_exist(self):
        """필수 테이블이 없으면 자동으로 생성"""
        if not self.db_conn:
            return
        
        try:
            # 필수 테이블 목록 확인
            cursor = self.db_conn.cursor()
            cursor.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_name IN ('messages', 'channels', 'users', 'gpt_analyses');
            """)
            existing_tables = {row[0] for row in cursor.fetchall()}
            cursor.close()
            
            required_tables = {'messages', 'channels', 'users', 'gpt_analyses'}
            missing_tables = required_tables - existing_tables
            
            if missing_tables:
                self._log(f"⚠️ 테이블 누락 감지: {', '.join(missing_tables)}")
                self._log("🔧 자동으로 테이블 생성 중...")
                
                # create_tables.sql 파일 읽기
                sql_file_path = os.path.join(os.path.dirname(__file__), 'sql', 'create_tables.sql')
                if os.path.exists(sql_file_path):
                    with open(sql_file_path, 'r', encoding='utf-8') as f:
                        sql_script = f.read()
                    
                    # SQL 스크립트 실행
                    cursor = self.db_conn.cursor()
                    try:
                        # 세미콜론으로 구분된 각 명령 실행
                        for statement in sql_script.split(';'):
                            statement = statement.strip()
                            if statement and not statement.startswith('--'):
                                cursor.execute(statement)
                        self.db_conn.commit()
                        cursor.close()
                        self._log("✅ 테이블 생성 완료!")
                    except Exception as e:
                        self.db_conn.rollback()
                        cursor.close()
                        self._log(f"⚠️ 테이블 생성 중 오류 발생: {str(e)[:200]}")
                        self._log("💡 수동으로 sql/create_tables.sql을 Supabase SQL Editor에서 실행하세요.")
                else:
                    self._log(f"⚠️ sql/create_tables.sql 파일을 찾을 수 없습니다.")
                    self._log("💡 수동으로 Supabase SQL Editor에서 테이블을 생성하세요.")
            else:
                self._log("✅ 모든 필수 테이블이 존재합니다.")
        except Exception as e:
            self._log(f"⚠️ 테이블 확인 중 오류: {str(e)[:200]}")
    
    def _update_progress(self, progress: float, status: str):
        """진행률 업데이트 (Streamlit 또는 무시)"""
        if self.progress_callback:
            self.progress_callback(progress, status)
            # Streamlit인 경우에만 UI 업데이트를 위한 대기
            # 터미널에서는 sleep이 필요 없으므로 제거
    
    def generate_weekly_analysis_report(self):
        """
        9월 1일부터 오늘까지의 메시지를 수집하고 월별로 분석하여
        CEO/관리자용 업무 분석 리포트 생성
        """
        self._log("=" * 80)
        self._log("📊 Slack 담당자별 월별 업무 분석 리포트 (CEO/관리자용)")
        self._log("=" * 80)
        self._log("")
        
        # 기간 설정 (9/1부터 또는 전월 1일부터)
        start_date, end_date = self.get_period_range()
        
        self._log(f"📅 조회 기간: {start_date.strftime('%Y년 %m월 %d일')} ~ {end_date.strftime('%Y년 %m월 %d일')}")
        self._log("")
        self._update_progress(0.05, "기간 설정 완료")
        
        # 모든 채널 가져오기
        self._update_progress(0.10, "채널 목록 수집 중...")
        channels = self.get_all_channels(exclude_archived=True)
        
        if not channels:
            self._log("❌ 수집할 채널이 없습니다.")
            return
        
        self._log("")
        self._log("=" * 80)
        self._log("📝 채널별 메시지 수집 시작...")
        self._log("=" * 80)
        self._log("")
        
        # 담당자별, 월별 메시지 저장
        # 구조: {user_name: {month_key: [{text, timestamp, channel, date, datetime}]}}
        user_monthly_messages = defaultdict(lambda: defaultdict(list))
        
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
            
            # 진행률 업데이트 (채널 수집 단계: 10% ~ 60%)
            channel_progress = 0.10 + (idx / total_channels) * 0.50
            self._update_progress(channel_progress, f"채널 수집 중 [{idx}/{total_channels}] {channel_type}{channel_name}")
            
            self._log(f"[{idx}/{total_channels}] {channel_type}{channel_name} 처리 중...")
            
            # 채널 정보 DB에 저장
            self.save_channel_to_db(channel)
            
            messages = self.get_period_messages(channel_id, channel_name, start_date, end_date)
            
            if messages:
                self._log(f"✅ {len(messages)}개 메시지 발견")
                
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
                        month_key = self.get_month_key(msg_time)
                        
                        user_monthly_messages[user_name][month_key].append({
                            "text": text,
                            "timestamp": ts,
                            "channel": channel_name,
                            "date": msg_time.date(),
                            "datetime": msg_time,
                            "user_id": user_id  # DB 조회용
                        })
            else:
                self._log("메시지 없음")
        
        self._log("")
        self._log("=" * 80)
        self._log("📊 메시지 수집 완료, GPT 분석 시작...")
        self._log("=" * 80)
        self._log("")
        self._update_progress(0.60, "메시지 수집 완료, GPT 분석 준비 중...")
        
        # 담당자별, 월별 GPT 분석 수행
        user_monthly_analysis = defaultdict(dict)
        
        total_users = len(user_monthly_messages)
        user_idx = 0
        
        # 전체 월 수 계산
        total_months = sum(len(months) for months in user_monthly_messages.values())
        analyzed_months = 0
        skipped_months = 0
        
        # 현재 날짜 확인 (중간일 때 현재 달 숨기기)
        kst = timezone(timedelta(hours=9))
        today = datetime.now(kst)
        current_month_key = self.get_month_key(today)
        
        for user_name, monthly_data in sorted(user_monthly_messages.items()):
            user_idx += 1
            months_in_user = len(monthly_data)
            
            self._log(f"[{user_idx}/{total_users}] 👤 {user_name} 분석 중...")
            
            for month_key in sorted(monthly_data.keys()):
                # 현재 달이고 15일 이전이면 스킵
                if month_key == current_month_key and today.day < 15:
                    skipped_months += 1
                    analyzed_months += 1
                    self._log(f"  → {month_key} ({len(monthly_data[month_key])}개 메시지) 현재 달 중간이라 스킵 ⏭️")
                    
                    # 진행률 업데이트 (GPT 분석 단계: 60% ~ 95%)
                    if total_months > 0:
                        analysis_progress = 0.60 + (analyzed_months / total_months) * 0.35
                        self._update_progress(analysis_progress, f"GPT 분석 진행 중 [{analyzed_months}/{total_months}] (스킵: {skipped_months})")
                    continue
                
                messages = monthly_data[month_key]
                
                # 월 시작일 계산
                year, month = map(int, month_key.split('-'))
                month_start = datetime(year, month, 1, 0, 0, 0, tzinfo=kst)
                month_range = f"{year}년 {month}월"
                
                # 사용자 ID 찾기 (첫 메시지에서)
                user_id = None
                if messages:
                    user_id = messages[0].get("user_id")
                
                # 중복 체크
                if user_id and self.check_existing_month(user_id, month_start):
                    skipped_months += 1
                    analyzed_months += 1
                    self._log(f"  → {month_key} ({month_range}, {len(messages)}개 메시지) 이미 분석됨 ⏭️")
                    
                    # 진행률 업데이트 (GPT 분석 단계: 60% ~ 95%)
                    if total_months > 0:
                        analysis_progress = 0.60 + (analyzed_months / total_months) * 0.35
                        self._update_progress(analysis_progress, f"GPT 분석 진행 중 [{analyzed_months}/{total_months}] (스킵: {skipped_months})")
                    continue
                
                # 진행률 업데이트
                if total_months > 0:
                    analysis_progress = 0.60 + (analyzed_months / total_months) * 0.35
                    self._update_progress(analysis_progress, f"GPT 분석 중 [{analyzed_months+1}/{total_months}] {user_name} - {month_range}")
                
                self._log(f"  → {month_key} ({month_range}, {len(messages)}개 메시지) 분석 중...")
                
                analysis = self.analyze_user_work_with_gpt(user_name, month_range, messages)
                
                if analysis:
                    analyzed_months += 1
                    user_monthly_analysis[user_name][month_key] = {
                        "analysis": analysis,
                        "message_count": len(messages),
                        "messages": messages,
                        "month_range": month_range,
                        "month_start": month_start
                    }
                    
                    # DB에 GPT 분석 결과 저장
                    if user_id:
                        self.save_gpt_analysis_to_db(user_id, month_start, month_range, analysis)
                    
                    self._log("✅")
                else:
                    analyzed_months += 1
                    self._log("⏭️")
        
        self._update_progress(0.95, "분석 완료, 리포트 생성 중...")
        self._log("")
        self._log("=" * 80)
        self._log("📋 CEO/관리자용 월별 업무 분석 리포트")
        self._log("=" * 80)
        self._log("")
        
        # 전체 요약 통계
        total_messages = sum(
            sum(data["message_count"] for data in user_data.values())
            for user_data in user_monthly_analysis.values()
        )
        
        self._log(f"분석된 담당자 수: {len(user_monthly_analysis)}명")
        self._log(f"총 메시지 수: {total_messages}개")
        self._log(f"분석 기간: {start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}")
        self._log(f"스킵된 월: {skipped_months}개")
        self._log("")
        
        # DB 저장 통계
        self._log("=" * 80)
        self._log("📊 DB 저장 통계")
        self._log("=" * 80)
        self._log(f"연결 상태: {self.db_connection_status}")
        if self.db_connection_type:
            self._log(f"연결 타입: {self.db_connection_type}")
        self._log("")
        self._log("저장 성공:")
        self._log(f"  - 메시지: {self.db_stats['messages_saved']}개")
        self._log(f"  - 채널: {self.db_stats['channels_saved']}개")
        self._log(f"  - 사용자: {self.db_stats['users_saved']}개")
        self._log(f"  - GPT 분석: {self.db_stats['analyses_saved']}개")
        self._log("")
        self._log("저장 실패:")
        self._log(f"  - 메시지: {self.db_stats['messages_failed']}개")
        self._log(f"  - 채널: {self.db_stats['channels_failed']}개")
        self._log(f"  - 사용자: {self.db_stats['users_failed']}개")
        self._log(f"  - GPT 분석: {self.db_stats['analyses_failed']}개")
        self._log("")
        self._log("=" * 80)
        self._log("✅ 리포트 생성 완료")
        self._log("=" * 80)
        self._update_progress(1.0, "✅ 완료!")


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
        reporter.generate_weekly_analysis_report()  # 함수명은 유지하지만 내부는 월별 분석
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
