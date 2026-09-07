"""테스트 공통 설정.

`app.core.database`는 import 시점에 settings.database_url로 엔진을 만든다.
대부분의 테스트는 자기 인메모리 엔진을 쓰지만 외부 커넥터나 운영 헬스체크
테스트는 모듈 레벨 엔진을 그대로 쓴다. 그래서 개발자 `.env`나 CI 기본값에 따라
테스트가 실제 PostgreSQL이나 Oracle에 붙으려다 실패하는 일이 있었다.

pytest는 테스트 모듈보다 conftest.py를 먼저 읽으니까, 여기서 환경변수를 미리
못박아두면 어느 환경에서 돌리든 SQLite 인메모리로 간다. pydantic-settings가
.env 파일보다 환경변수를 우선하는 걸 이용한 거다.
"""
import os

# app.* 를 import 하기 전에 설정해야 효과가 있다.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# 외부 연동은 테스트에서 호출되면 안 되니 키를 비워 미설정 경로로 보낸다.
for _key in ("ODOO_PASSWORD", "ODOO_API_KEY", "GEMINI_API_KEY",
             "KMA_API_KEY", "HOLIDAY_API_KEY", "NARA_API_KEY", "PPS_API_KEY"):
    os.environ[_key] = ""

# LLM은 규칙 폴백을 타야 결과가 항상 같다. 네트워크 의존을 없앤다.
os.environ["LLM_PROVIDER"] = "rule"
