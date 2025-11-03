# -*- coding: utf-8 -*-
"""
네트워크 및 DNS 테스트 스크립트
"""

import os
import sys
import socket
import io

# Windows 콘솔 인코딩 문제 해결
if sys.platform == "win32":
    try:
        os.system('chcp 65001 >nul 2>&1')
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    except:
        pass

def test_dns(hostname):
    """DNS 해석 테스트"""
    print(f"🔍 DNS 해석 테스트: {hostname}")
    try:
        ip = socket.gethostbyname(hostname)
        print(f"   ✅ DNS 해석 성공: {ip}")
        return True
    except socket.gaierror as e:
        print(f"   ❌ DNS 해석 실패: {e}")
        return False

def test_connection(hostname, port):
    """포트 연결 테스트"""
    print(f"🔌 연결 테스트: {hostname}:{port}")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((hostname, port))
        sock.close()
        
        if result == 0:
            print(f"   ✅ 포트 {port} 연결 가능")
            return True
        else:
            print(f"   ❌ 포트 {port} 연결 실패 (코드: {result})")
            return False
    except Exception as e:
        print(f"   ❌ 연결 테스트 실패: {e}")
        return False

def main():
    """메인 함수"""
    print("=" * 80)
    print("🌐 네트워크 및 DNS 테스트")
    print("=" * 80)
    print()
    
    # 환경 변수 확인
    db_connection_string = os.getenv("DB_CONNECTION_STRING")
    
    if not db_connection_string:
        print("❌ DB_CONNECTION_STRING 환경 변수가 설정되지 않았습니다.")
        return
    
    # 연결 문자열 파싱
    try:
        # postgresql://postgres:password@host:port/database 형식
        parts = db_connection_string.replace("postgresql://", "").split("@")
        if len(parts) == 2:
            user_pass = parts[0]
            host_db = parts[1]
            host_port = host_db.split("/")[0]
            hostname = host_port.split(":")[0]
            port = int(host_port.split(":")[1]) if ":" in host_port else 5432
            
            print(f"📋 연결 정보 분석:")
            print(f"   호스트명: {hostname}")
            print(f"   포트: {port}")
            print()
            
            # DNS 테스트
            dns_ok = test_dns(hostname)
            print()
            
            if dns_ok:
                # IP 주소로 직접 연결 테스트
                try:
                    ip = socket.gethostbyname(hostname)
                    print(f"💡 IP 주소로 직접 연결 테스트: {ip}:{port}")
                    connection_ok = test_connection(ip, port)
                    print()
                except:
                    connection_ok = False
            else:
                connection_ok = False
            
            # 결과 요약
            print("=" * 80)
            if dns_ok and connection_ok:
                print("✅ 네트워크 연결 정상")
                print("   Supabase 연결 문자열은 올바르지만, 다른 문제가 있을 수 있습니다.")
            elif dns_ok:
                print("⚠️ DNS는 해석되지만 포트 연결 실패")
                print("   방화벽이나 Supabase 프로젝트 설정을 확인하세요.")
            else:
                print("❌ DNS 해석 실패")
                print("   호스트명이 잘못되었거나 네트워크 문제가 있을 수 있습니다.")
                print()
                print("확인 사항:")
                print("1. Supabase 대시보드에서 연결 정보 재확인")
                print("2. 호스트명이 올바른지 확인")
                print("3. 인터넷 연결 확인")
                print("4. VPN이나 프록시 설정 확인")
            
        else:
            print("❌ 연결 문자열 형식이 올바르지 않습니다.")
            print("   예상 형식: postgresql://user:password@host:port/database")
    
    except Exception as e:
        print(f"❌ 연결 문자열 파싱 오류: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

