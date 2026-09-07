"""요청 로그를 메모리에 쌓아두는 링버퍼와 수집 미들웨어.

운영 화면의 '로그 확인' 탭이 여기서 데이터를 가져간다.

파일 대신 메모리를 쓴 이유는, 운영자가 알고 싶은 게 대개 '방금 뭐가 느렸나',
'뭐가 500을 냈나' 정도라서다. 파일을 tail 하려면 SSH를 해야 하는데 링버퍼는
브라우저에서 바로 보인다. deque maxlen으로 크기가 고정이라 메모리도 안 샌다.
재시작하면 비워지는데 이건 의도한 거다.

오래 보관해야 하면 이 자리를 CloudWatch Logs로 바꾸면 된다.
"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# 최근 N건만 유지 — 넘치면 오래된 것부터 자동 폐기
MAX_RECORDS = 500

_records: deque[dict[str, Any]] = deque(maxlen=MAX_RECORDS)

# 프로세스 기동 시각 — uptime 계산용
STARTED_AT = datetime.now(timezone.utc)

# 헬스체크·정적 요청까지 남기면 로그가 잡음으로 가득 찬다 → 제외
_SKIP_PATHS = {"/health", "/favicon.ico", "/api/ops/logs"}


def add_record(rec: dict[str, Any]) -> None:
    _records.append(rec)


def get_records(limit: int = 100, level: str | None = None,
                path_contains: str | None = None) -> list[dict[str, Any]]:
    """최신순으로 반환. level='error'면 4xx/5xx만, 'slow'면 느린 요청만."""
    rows = list(_records)[::-1]
    if level == "error":
        rows = [r for r in rows if r["status_code"] >= 400]
    elif level == "slow":
        rows = [r for r in rows if r["slow"]]
    if path_contains:
        rows = [r for r in rows if path_contains in r["path"]]
    return rows[:limit]


def stats() -> dict[str, Any]:
    """요청 통계 — 총건수·에러율·평균/최대 응답시간."""
    rows = list(_records)
    if not rows:
        return {"total": 0, "error_count": 0, "error_rate_pct": 0.0,
                "avg_ms": 0.0, "max_ms": 0.0, "slow_count": 0}
    errs = [r for r in rows if r["status_code"] >= 400]
    durations = [r["duration_ms"] for r in rows]
    return {
        "total": len(rows),
        "error_count": len(errs),
        "error_rate_pct": round(100 * len(errs) / len(rows), 2),
        "avg_ms": round(sum(durations) / len(durations), 1),
        "max_ms": round(max(durations), 1),
        "slow_count": sum(1 for r in rows if r["slow"]),
    }


def clear() -> int:
    n = len(_records)
    _records.clear()
    return n


class RequestLogMiddleware(BaseHTTPMiddleware):
    """모든 요청의 경로·상태코드·소요시간을 링버퍼에 쌓는다.

    slow_ms를 넘으면 slow=True로 찍어서 운영 화면에서 걸러 볼 수 있다.
    예외가 나도 기록은 남기고 그대로 다시 던진다. 로깅이 장애를 삼키면 안 된다.
    """

    def __init__(self, app: ASGIApp, slow_ms: float = 1000.0):
        super().__init__(app)
        self.slow_ms = slow_ms

    async def dispatch(self, request, call_next):
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        started = time.perf_counter()
        status_code = 500
        error: str | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as e:                       # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            add_record({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": round(elapsed, 1),
                "slow": elapsed >= self.slow_ms,
                "error": error,
                "client": request.client.host if request.client else None,
            })
