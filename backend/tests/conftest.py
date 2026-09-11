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

import pytest

# app.* 를 import 하기 전에 설정해야 효과가 있다.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# 외부 연동은 테스트에서 호출되면 안 되니 키를 비워 미설정 경로로 보낸다.
for _key in ("ODOO_PASSWORD", "ODOO_API_KEY", "GEMINI_API_KEY",
             "KMA_API_KEY", "HOLIDAY_API_KEY", "NARA_API_KEY", "PPS_API_KEY"):
    os.environ[_key] = ""

# LLM은 규칙 폴백을 타야 결과가 항상 같다. 네트워크 의존을 없앤다.
os.environ["LLM_PROVIDER"] = "rule"

# 테스트가 저장소에 로그 파일을 남기지 않게 한다.
os.environ["LOG_DIR"] = ""

# 로그인 테스트(test_auth.py)가 쓸 계정. 개발자 .env 값과 상관없이 고정한다.
os.environ["AUTH_SECRET"] = "test-secret"
os.environ["AUTH_ADMIN_USERNAME"] = "admin"
os.environ["AUTH_ADMIN_PASSWORD"] = "admin-pw"
os.environ["AUTH_VIEWER_USERNAME"] = "viewer"
os.environ["AUTH_VIEWER_PASSWORD"] = "viewer-pw"


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: 관리자 대역 없이 실제 로그인으로 본다")


@pytest.fixture(autouse=True)
def _as_admin(request):
    """기존 테스트는 업무 로직을 본다. 로그인은 test_auth.py 가 따로 본다.

    그래서 기본은 관리자로 로그인한 것처럼 인증 의존성을 바꿔 둔다.
    `real_auth` 표시가 붙은 테스트만 실제 토큰 검사를 탄다."""
    if request.node.get_closest_marker("real_auth"):
        yield
        return
    from app.core.auth import optional_user, require_user
    from app.main import app

    admin = {"sub": "test", "role": "admin", "exp": 2**31}
    app.dependency_overrides[require_user] = lambda: admin
    app.dependency_overrides[optional_user] = lambda: admin
    yield
    app.dependency_overrides.pop(require_user, None)
    app.dependency_overrides.pop(optional_user, None)
