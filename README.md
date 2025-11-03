# Slack 업무 분석 대시보드

Slack 메시지를 수집하고 GPT를 활용하여 CEO/관리자용 업무 분석 리포트를 생성하는 Streamlit 대시보드입니다.

## 기능

- 🔍 Slack 채널별 메시지 수집 (공개/비공개 채널, DM 포함)
- 🤖 GPT 기반 주간 업무 분석
- 📊 CEO 친화적 대시보드 UI
- 💾 Supabase를 통한 데이터 저장 및 중복 방지
- 🔐 로그인 인증 기능
- 📥 JSON/Markdown 리포트 다운로드

## 설치 및 실행

### 로컬 실행

1. 의존성 설치
```bash
pip install -r requirements.txt
```

2. 환경 변수 설정 (`.streamlit/secrets.toml`)
```toml
SLACK_USER_TOKEN = "xoxp-your-token"
OPENAI_API_KEY = "sk-your-api-key"
DB_CONNECTION_STRING = "postgresql://postgres:password@host:5432/postgres"
LOGIN_USERNAME = "master"
LOGIN_PASSWORD = "your-password"
```

3. Supabase 테이블 생성
```bash
# sql/create_tables.sql 파일의 내용을 Supabase SQL Editor에서 실행
```

4. Streamlit 실행
```bash
streamlit run app.py
```

## Streamlit Cloud 배포

1. [Streamlit Cloud](https://streamlit.io/cloud)에 접속하여 GitHub 저장소를 연결
2. Settings > Secrets에서 다음 값 설정:
   ```
   SLACK_USER_TOKEN = "xoxp-your-token"
   OPENAI_API_KEY = "sk-your-api-key"
   DB_CONNECTION_STRING = "postgresql://postgres:password@host:5432/postgres"
   LOGIN_USERNAME = "master"
   LOGIN_PASSWORD = "your-password"
   ```
3. Main file path: `app.py`로 설정
4. Deploy!

## 사용 방법

1. 로그인 (기본: master / bnk1122*)
2. 사이드바에서 "데이터 수집 및 분석 실행" 클릭
3. 담당자 선택하여 상세 리포트 확인
4. JSON 또는 Markdown 형식으로 다운로드

## 주의사항

- Supabase 테이블은 먼저 생성되어 있어야 합니다
- Slack User Token에 필요한 권한:
  - `channels:read`
  - `channels:history`
  - `groups:read`
  - `groups:history`
  - `im:read`
  - `mpim:read`
  - `users:read`
