"""로그인과 권한.

계정은 두 개다. 관리자(admin)는 전부 할 수 있고, 조회 계정(viewer)은 읽기만 한다.
계획서 FR-11 "관리자 로그인, 조회 전용 계정 분리" 그대로다.

계정을 DB 테이블로 두지 않고 환경변수로 받는다. 단일 기업 내부 도구라 사용자가
두 명 수준이고, 테이블로 만들면 가입·비밀번호 변경 화면까지 따라와야 한다.
비밀번호는 다른 비밀값처럼 SSM → .env 로 들어온다.

토큰은 HMAC-SHA256 으로 서명한 짧은 문자열이다. JWT 라이브러리를 안 쓴 건
필요한 게 "누가, 어떤 권한으로, 언제까지" 세 가지뿐이라서다. 의존성을 하나 늘리면
pip-audit 가 볼 것도 하나 는다.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

log = logging.getLogger(__name__)

ROLES = ("admin", "viewer")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# POST 지만 데이터를 바꾸지 않는 경로. 조회 계정도 쓸 수 있다.
# 챗봇은 질문을 POST 로 보낼 뿐 DB 를 고치지 않는다.
READ_ONLY_POSTS = {"/api/chat"}

# 로그인 실패 제한. 계정별로 60초에 5번까지만 틀릴 수 있다.
# IP 로 세지 않는 이유: Caddy 뒤라 모든 요청이 같은 주소에서 온다.
MAX_FAILURES = 5
FAILURE_WINDOW_SEC = 60
_failures: dict[str, deque[float]] = defaultdict(deque)

# 서명 키가 없으면 프로세스마다 새로 만든다. 재시작하면 다시 로그인해야 하지만
# 빈 키로 서명하는 것보다는 낫다.
_fallback_key = secrets.token_bytes(32)
if not settings.auth_secret:
    log.warning("AUTH_SECRET 이 비어 있어 임시 키로 서명한다. 재시작하면 로그인이 풀린다.")

_bearer = HTTPBearer(auto_error=False, description="POST /api/auth/login 으로 받은 토큰")


def _key() -> bytes:
    return settings.auth_secret.encode() if settings.auth_secret else _fallback_key


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64(hmac.new(_key(), body.encode(), hashlib.sha256).digest())


def _accounts() -> dict[str, tuple[str, str]]:
    """아이디 → (비밀번호, 권한). 비밀번호가 빈 계정은 없는 것으로 친다."""
    accounts = {}
    if settings.auth_viewer_password:
        accounts[settings.auth_viewer_username] = (settings.auth_viewer_password, "viewer")
    if settings.auth_admin_password:
        accounts[settings.auth_admin_username] = (settings.auth_admin_password, "admin")
    return accounts


def throttled(username: str, now: float | None = None) -> bool:
    now = now or time.time()
    q = _failures[username]
    while q and q[0] < now - FAILURE_WINDOW_SEC:
        q.popleft()
    return len(q) >= MAX_FAILURES


def authenticate(username: str, password: str) -> str | None:
    """맞으면 권한을, 틀리면 None 을 돌려준다."""
    entry = _accounts().get(username)
    # 없는 계정이어도 비교는 한 번 한다. 응답 시간으로 계정이 있는지 드러나지 않게.
    expected = entry[0] if entry else secrets.token_hex(16)
    ok = hmac.compare_digest(password.encode(), expected.encode())
    if entry and ok:
        _failures.pop(username, None)
        return entry[1]
    _failures[username].append(time.time())
    return None


def issue_token(username: str, role: str, now: float | None = None) -> tuple[str, int]:
    exp = int((now or time.time()) + settings.auth_token_hours * 3600)
    claims = {"sub": username, "role": role, "exp": exp}
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    return f"{body}.{_sign(body)}", exp


def verify_token(token: str) -> dict | None:
    body, _, sig = token.partition(".")
    if not sig or not hmac.compare_digest(sig, _sign(body)):
        return None
    try:
        claims = json.loads(_unb64(body))
    except ValueError:
        return None
    if not isinstance(claims, dict) or claims.get("exp", 0) < time.time():
        return None
    # 비밀번호를 지워 계정을 막았거나 권한이 바뀌었으면, 이미 나간 토큰도 무효로 한다.
    entry = _accounts().get(claims.get("sub"))
    if entry is None or entry[1] != claims.get("role"):
        return None
    return claims


def require_user(
    request: Request,
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """보호된 API 전부에 붙는다. 조회 계정은 읽기 요청만 통과시킨다."""
    claims = verify_token(cred.credentials) if cred else None
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요합니다.",
                            headers={"WWW-Authenticate": "Bearer"})
    if (request.method not in SAFE_METHODS and claims["role"] != "admin"
            and request.url.path not in READ_ONLY_POSTS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "조회 계정은 데이터를 바꿀 수 없습니다.")
    return claims


def optional_user(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """공개 API 가 로그인한 사람에게만 더 보여줄 때 쓴다."""
    return verify_token(cred.credentials) if cred else None
