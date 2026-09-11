"""make health / make check 가 쓸 관리자 토큰을 받는다.

.env 의 AUTH_ADMIN_USERNAME·AUTH_ADMIN_PASSWORD 로 로그인해서 토큰만 출력한다.
표준 라이브러리만 쓴다. 서버 호스트에는 앱 의존성이 깔려 있지 않아서다.

  python3 scripts/api_token.py                          # localhost:8000
  STOCKCAST_URL=https://<도메인> python3 scripts/api_token.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ENV = Path(__file__).resolve().parents[1] / ".env"


def read_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                env[key.strip()] = value.split(" #", 1)[0].strip()
    return env


def main() -> int:
    env = read_env()
    body = json.dumps({"username": env.get("AUTH_ADMIN_USERNAME") or "admin",
                       "password": env.get("AUTH_ADMIN_PASSWORD", "")}).encode()
    url = os.getenv("STOCKCAST_URL", "http://localhost:8000").rstrip("/") + "/api/auth/login"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(json.load(resp)["access_token"])
    except (urllib.error.URLError, KeyError, ValueError) as e:
        print(f"로그인 실패: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
