"""요청 로그를 메모리에 쌓아두는 링버퍼와 수집 미들웨어.

운영 화면의 '로그 확인' 탭이 여기서 데이터를 가져간다.

화면은 메모리 링버퍼를 읽는다. 운영자가 알고 싶은 게 대개 '방금 뭐가 느렸나',
'뭐가 500을 냈나' 정도라서다. deque maxlen으로 크기가 고정이라 메모리도 안 샌다.

같은 기록을 파일(LOG_DIR/requests.log)에도 한 줄씩 남긴다. 링버퍼만 쓰면 재시작할
때 비는데, 장애 원인은 바로 그 재시작 직전에 있기 때문이다. 앱이 다시 뜨면 파일의
최근 기록을 링버퍼로 되살려서, 워치독이 되살린 뒤에도 왜 죽었는지 화면에서 보인다.
파일은 5MB씩 5개까지 돌려 쓴다.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.core.config import settings

# 최근 N건만 유지 — 넘치면 오래된 것부터 자동 폐기
MAX_RECORDS = 500

_records: deque[dict[str, Any]] = deque(maxlen=MAX_RECORDS)

_file_log = logging.getLogger("stockcast.requests")
_file_log.propagate = False
_file_log.setLevel(logging.INFO)

# 프로세스 기동 시각 — uptime 계산용
STARTED_AT = datetime.now(timezone.utc)

# 헬스체크·정적 요청까지 남기면 로그가 잡음으로 가득 찬다 → 제외
_SKIP_PATHS = {"/health", "/favicon.ico", "/api/ops/logs"}


def enable_file_log(log_dir: str) -> Path | None:
    """파일 기록을 켜고, 링버퍼가 비어 있으면 파일의 최근 기록으로 채운다."""
    for h in list(_file_log.handlers):
        _file_log.removeHandler(h)
        h.close()
    if not log_dir:
        return None
    path = Path(log_dir) / "requests.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not _records:
        with path.open(encoding="utf-8") as f:
            for line in deque(f, maxlen=MAX_RECORDS):
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue      # 쓰다 끊긴 줄은 버린다
                if isinstance(rec, dict) and "status_code" in rec:
                    _records.append(rec)
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    _file_log.addHandler(handler)
    return path


def add_record(rec: dict[str, Any]) -> None:
    _records.append(rec)
    if _file_log.handlers:
        _file_log.info(json.dumps(rec, ensure_ascii=False))


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
        try:
            enable_file_log(settings.log_dir)
        except OSError as e:
            # 디스크 권한 문제로 앱이 안 뜨면 안 된다. 메모리 기록만으로 계속 간다.
            logging.getLogger(__name__).warning("요청 로그 파일을 못 연다: %s", e)

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
