"""외부 데이터 정기 수집 스케줄러 (로컬 실행용).

운영(AWS)에서는 EventBridge + Lambda로 대체하지만, 로컬/단일 서버에서는
이 스크립트를 cron 또는 APScheduler로 돌려 동일한 수집을 수행한다.

사용:
  python -m app.scheduler            # 어제~오늘 날씨 + 올해 공휴일 1회 수집
  python -m app.scheduler --daemon   # APScheduler로 매일 06:00 자동 수집
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta

from app.core.database import SessionLocal
from app.services.external import collect_holidays, collect_weather


def run_once() -> None:
    db = SessionLocal()
    try:
        end = date.today()
        start = end - timedelta(days=1)
        w = collect_weather(db, start, end)
        h = collect_holidays(db, end.year)
        print(f"[수집] 날씨 {w}, 공휴일 {h}")
    finally:
        db.close()


def run_daemon() -> None:
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
    except ImportError:
        raise SystemExit("apscheduler 미설치: pip install apscheduler")
    sched = BlockingScheduler(timezone="Asia/Seoul")
    sched.add_job(run_once, "cron", hour=6, minute=0, id="daily_external")
    print("스케줄러 시작: 매일 06:00 (Asia/Seoul) 외부 데이터 수집")
    sched.start()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--daemon", action="store_true", help="APScheduler 데몬 실행")
    args = p.parse_args()
    run_daemon() if args.daemon else run_once()
