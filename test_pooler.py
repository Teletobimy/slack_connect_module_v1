# -*- coding: utf-8 -*-
"""
Supabase Session Pooler 연결 테스트 스크립트
IPv4 네트워크에서 사용하는 Pooler 연결 테스트
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

def test_pooler_connection():
    """Session Pooler 연결 테스트"""
    print("=" * 80)
    print("🔍 Supabase Session Pooler 연결 테스트 (IPv4 호환)")
    print("=" * 80)
    print()
    
    # 환경 변수 확인
    db_connection_string = os.getenv("DB_CONNECTION_STRING")
    
    if not db_connection_string:
        print("❌ DB_CONNECTION_STRING 환경 변수가 설정되지 않았습니다.")
        return False
    
    print(f"✅ 기존 연결 문자열 확인됨")
    print(f"   {db_connection_string[:80]}...")
    print()
    
    # Session Pooler 연결 문자열로 변환 (포트 6543 사용)
    # Direct connection: postgresql://postgres:password@host:5432/postgres
    # Session Pooler: postgresql://postgres:password@host:6543/postgres
    # 포트만 변경 (쿼리 파라미터 없음)
    if ":5432/" in db_connection_string:
        pooler_string = db_connection_string.replace(":5432/", ":6543/postgres")
    elif ":5432" in db_connection_string:
        pooler_string = db_connection_string.replace(":5432", ":6543")
    else:
        # 포트가 없거나 다른 경우, 기본 포트를 6543으로 설정
        if "@" in db_connection_string and ":" not in db_connection_string.split("@")[1].split("/")[0]:
            # 호스트명 뒤에 포트가 없는 경우 추가
            pooler_string = db_connection_string.replace("@db.", "@db.:6543")
        else:
            pooler_string = db_connection_string
    
    print(f"🔄 Session Pooler 연결 문자열 생성:")
    print(f"   {pooler_string[:80]}...")
    print()
    
    try:
        print("🔌 Session Pooler에 연결 시도 중...")
        
        # 연결 시도
        conn = connect(pooler_string)
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        
        print("✅ Session Pooler 연결 성공!")
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
            for table in tables[:10]:  # 최대 10개만 표시
                print(f"      - {table[0]}")
            if len(tables) > 10:
                print(f"      ... 외 {len(tables) - 10}개")
        else:
            print("   ⚠️ 테이블이 없습니다. sql/create_tables.sql을 실행해야 합니다.")
        print()
        
        cursor.close()
        conn.close()
        
        print("=" * 80)
        print("✅ Session Pooler 테스트 완료!")
        print("=" * 80)
        print()
        print("💡 이 연결 문자열을 사용하세요:")
        print(f"   {pooler_string}")
        print()
        return True
        
    except Exception as e:
        print(f"❌ Session Pooler 연결 실패: {e}")
        print()
        print("다른 방법:")
        print("1. Supabase 대시보드에서 Session Pooler 연결 문자열 직접 확인")
        print("2. IPv4 add-on 구매 고려")
        print("3. VPN을 통해 IPv6 네트워크 접근")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    test_pooler_connection()

