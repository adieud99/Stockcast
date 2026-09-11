"""외부 데이터 정기 수집 스케줄러.

docker compose 의 scheduler 서비스가 --daemon 으로 띄운다. 날씨·공휴일·입찰공고·
계약단가를 받아 쌓는다. 계획서 FR-05 "일 1회 수집, 실패 시 재시도와 기록"을 맡는다.

API 서버 안에 넣지 않고 따로 띄웠다. uvicorn 워커가 늘면 수집도 워커 수만큼
중복으로 돌고, 수집이 죽어도 API 는 어제 데이터로 계속 돌아야 해서다.

도는 시점은 두 번이다.
  - 매일 06:00 (서울)
  - 컨테이너가 뜰 때 한 번. 서버를 필요할 때만 켜므로 06:00 에 꺼져 있으면
    그날 수집이 통째로 빠진다. 수집은 전부 멱등이라 여러 번 돌아도 괜찮다.

사용:
  python -m app.scheduler            # 지금 한 번 수집
  python -m app.scheduler --daemon   # 뜰 때 한 번 + 매일 06:00
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable
from datetime import date, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.services.external import collect_holidays, collect_weather
from app.services.nara import collect_bid_notices
from app.services.pps import collect_shop_prices

log = logging.getLogger("stockcast.collect")

RETRIES = 3
BACKOFF_SEC = 60   # 1분, 2분 뒤 다시. 공공 API 는 잠깐 죽었다 살아나는 일이 잦다

Job = Callable[[Session], dict]


def jobs(today: date) -> list[tuple[str, Job]]:
    yesterday = today - timedelta(days=1)
    return [
        # ASOS 일자료는 전날까지만 나온다. 이틀치를 받아 하루 빠진 날도 메운다.
        ("날씨", lambda db: collect_weather(db, yesterday - timedelta(days=1), yesterday)),
        ("공휴일", lambda db: collect_holidays(db, today.year)),
        # 조회기간이 한 달로 제한된다. 사흘치를 받아 merge 로 중복을 없앤다.
        ("입찰공고", lambda db: collect_bid_notices(db, today - timedelta(days=3), today, rows=300)),
        ("계약단가", lambda db: collect_shop_prices(db, days=7, rows=100)),
    ]


def run_job(label: str, fn: Job, retries: int = RETRIES, backoff: float = BACKOFF_SEC,
            sleep: Callable[[float], None] = time.sleep) -> dict:
    """커넥터 하나를 돌린다. 실패하면 새 세션으로 다시 시도한다.

    커넥터는 네트워크 오류를 예외 대신 failed=True 로 돌려준다. 예외(파싱·DB 오류)도
    같이 받아서 롤백한다. 한 커넥터가 죽어도 나머지는 돌아야 한다."""
    reason = ""
    for attempt in range(1, retries + 1):
        db = SessionLocal()
        try:
            r = fn(db)
            if not r.get("failed"):
                log.info("%s 수집 %s건 — %s", label, r.get("collected", 0), r.get("message", ""))
                return {"label": label, "ok": True, "attempts": attempt, **r}
            reason = r.get("message", "")
        except Exception as e:  # noqa: BLE001
            db.rollback()
            reason = f"{type(e).__name__}: {e}"
        finally:
            db.close()
        log.warning("%s 수집 실패 (%d/%d) — %s", label, attempt, retries, reason)
        if attempt < retries:
            sleep(backoff * attempt)
    log.error("%s 수집 포기 — %d번 모두 실패", label, retries)
    return {"label": label, "ok": False, "attempts": retries, "message": reason}


def run_once(today: date | None = None, **kw) -> list[dict]:
    results = [run_job(label, fn, **kw) for label, fn in jobs(today or date.today())]
    ok = sum(r["ok"] for r in results)
    log.info("수집 끝 — %d/%d 성공", ok, len(results))
    return results


def setup_logging() -> None:
    """표준출력(docker logs)과 파일 둘 다 남긴다. 파일은 컨테이너를 다시 만들어도 남는다."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.log_dir:
        Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(Path(settings.log_dir) / "collect.log",
                                            maxBytes=1_000_000, backupCount=5, encoding="utf-8"))
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def run_daemon() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    run_once()
    sched = BlockingScheduler(timezone="Asia/Seoul")
    # 06:00 에 잠깐 죽어 있었어도 한 시간 안에 살아나면 밀린 걸 한 번만 돌린다.
    sched.add_job(run_once, "cron", hour=6, minute=0, id="daily_external",
                  misfire_grace_time=3600, coalesce=True)
    log.info("스케줄러 시작: 매일 06:00 (Asia/Seoul)")
    sched.start()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--daemon", action="store_true", help="뜰 때 한 번 + 매일 06:00")
    args = p.parse_args()
    setup_logging()
    run_daemon() if args.daemon else run_once()
