# -*- coding: utf-8 -*-
"""
Supabase 연결 테스트 스크립트
"""

import os
import sys
import io
from psycopg2 import connect
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Windows 콘솔 인코딩 문제 해결
if sys.platform == "win32":
    try:
        os.system('chcp 65001 >nul 2>&1')
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except:
        pass

def test_supabase_connection():
    """Supabase 연결 테스트"""
    print("=" * 80)
    print("🔍 Supabase 연결 테스트")
    print("=" * 80)
    print()
    
    # 환경 변수 확인
    db_connection_string = os.getenv("DB_CONNECTION_STRING")
    
    if not db_connection_string:
        print("❌ DB_CONNECTION_STRING 환경 변수가 설정되지 않았습니다.")
        print("\n설정 방법:")
        print('   $env:DB_CONNECTION_STRING="postgresql://postgres:password@host:5432/postgres"')
        return False
    
    print(f"✅ 연결 문자열 확인됨")
    print(f"   연결 문자열: {db_connection_string[:50]}...")
    print()
    
    try:
        print("🔌 Supabase에 연결 시도 중...")
        
        # 연결 시도
        conn = connect(db_connection_string)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        print("✅ 연결 성공!")
        print()
        
        # 커서 생성
        cursor = conn.cursor()
        
        # PostgreSQL 버전 확인
        print("📊 PostgreSQL 버전 확인...")
        cursor.execute("SELECT version();")
        version = cursor.fetchone()[0]
        print(f"   버전: {version.split(',')[0]}")
        print()
        
        # 테이블 목록 확인
        print("📋 테이블 목록 확인...")
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()
        
        if tables:
            print(f"   ✅ 총 {len(tables)}개의 테이블 발견:")
            for table in tables:
                print(f"      - {table[0]}")
        else:
            print("   ⚠️ 테이블이 없습니다. sql/create_tables.sql을 실행해야 합니다.")
        print()
        
        # 필요한 테이블 확인
        required_tables = ['messages', 'channels', 'users', 'sync_channel_state', 'sync_thread_state', 'metrics_weekly', 'gpt_analyses']
        print("🔍 필수 테이블 확인...")
        existing_tables = [table[0] for table in tables]
        
        for req_table in required_tables:
            if req_table in existing_tables:
                # 테이블의 행 수 확인
                cursor.execute(f"SELECT COUNT(*) FROM {req_table};")
                count = cursor.fetchone()[0]
                print(f"   ✅ {req_table}: 존재함 ({count}개 행)")
            else:
                print(f"   ❌ {req_table}: 존재하지 않음")
        print()
        
        # messages 테이블 샘플 확인
        if 'messages' in existing_tables:
            print("📝 messages 테이블 샘플 확인...")
            cursor.execute("SELECT msg_uid, channel_id, ts, user_id, LEFT(text, 50) as text_sample FROM messages LIMIT 5;")
            samples = cursor.fetchall()
            
            if samples:
                print(f"   ✅ {len(samples)}개 샘플 발견:")
                for sample in samples:
                    msg_uid, channel_id, ts, user_id, text_sample = sample
                    print(f"      - {msg_uid}: channel={channel_id}, user={user_id}, text={text_sample}...")
            else:
                print("   ⚠️ messages 테이블이 비어있습니다.")
            print()
        
        # gpt_analyses 테이블 샘플 확인
        if 'gpt_analyses' in existing_tables:
            print("🤖 gpt_analyses 테이블 확인...")
            cursor.execute("SELECT COUNT(*) FROM gpt_analyses;")
            count = cursor.fetchone()[0]
            print(f"   ✅ {count}개의 분석 결과가 저장되어 있습니다.")
            
            if count > 0:
                cursor.execute("""
                    SELECT user_id, week_start, week_range 
                    FROM gpt_analyses 
                    ORDER BY week_start DESC 
                    LIMIT 5;
                """)
                analyses = cursor.fetchall()
                print("   최근 분석 결과:")
                for analysis in analyses:
                    user_id, week_start, week_range = analysis
                    print(f"      - user_id={user_id}, week={week_range}, start_date={week_start}")
            print()
        
        cursor.close()
        conn.close()
        
        print("=" * 80)
        print("✅ 모든 테스트 완료!")
        print("=" * 80)
        return True
        
    except Exception as e:
        print(f"❌ 연결 실패: {e}")
        print()
        print("문제 해결 방법:")
        print("1. 연결 문자열이 올바른지 확인")
        print("2. Supabase 프로젝트가 활성화되어 있는지 확인")
        print("3. 방화벽이나 네트워크 설정 확인")
        print("4. Supabase 대시보드에서 연결 정보 재확인")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_supabase_connection()

