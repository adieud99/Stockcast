"""수집 스케줄러(FR-05)와 요청 로그 파일 보관 테스트."""
from datetime import date

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import scheduler
from app.core import logbuffer
from app.core.database import Base
from app.models.mm import ExtShopPrice
from app.services import pps


def test_retries_until_success():
    calls, sleeps = [], []

    def flaky(db):
        calls.append(1)
        if len(calls) < 2:
            return {"collected": 0, "has_api_key": True, "failed": True, "message": "타임아웃"}
        return {"collected": 3, "has_api_key": True, "message": "수집 완료"}

    r = scheduler.run_job("테스트", flaky, retries=3, backoff=10, sleep=sleeps.append)
    assert r["ok"] and r["attempts"] == 2 and r["collected"] == 3
    assert sleeps == [10]


def test_exception_gives_up_after_retries():
    sleeps = []

    def broken(db):
        raise KeyError("응답 형식이 바뀜")

    r = scheduler.run_job("테스트", broken, retries=3, backoff=5, sleep=sleeps.append)
    assert not r["ok"] and r["attempts"] == 3
    assert "KeyError" in r["message"]
    assert sleeps == [5, 10]


def test_missing_key_is_not_retried():
    sleeps = []
    r = scheduler.run_job("테스트", lambda db: {"collected": 0, "has_api_key": False,
                                                "message": "미설정"}, sleep=sleeps.append)
    assert r["ok"] and r["attempts"] == 1 and sleeps == []


def test_jobs_cover_four_sources():
    labels = [label for label, _ in scheduler.jobs(date(2026, 9, 11))]
    assert labels == ["날씨", "공휴일", "입찰공고", "계약단가"]


def test_empty_price_response_keeps_existing_prices(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(ExtShopPrice(spec_name="기존 단가", contract_price=1000))
    db.commit()

    monkeypatch.setattr(pps.settings, "pps_api_key", "k")
    monkeypatch.setattr(pps, "fetch_mas_products", lambda *a, **kw: [])
    r = pps.collect_shop_prices(db)
    assert r["collected"] == 0
    assert db.scalar(select(func.count()).select_from(ExtShopPrice)) == 1


def test_request_log_survives_restart(tmp_path):
    logbuffer.clear()
    logbuffer.enable_file_log(str(tmp_path))
    logbuffer.add_record({"ts": "2026-09-11T00:00:00+00:00", "method": "GET",
                          "path": "/api/kpi/summary", "status_code": 500,
                          "duration_ms": 12.0, "slow": False, "error": "boom", "client": None})
    # 재시작 흉내: 메모리가 비고 파일만 남는다
    logbuffer.clear()
    logbuffer.enable_file_log(str(tmp_path))
    rows = logbuffer.get_records(level="error")
    assert rows and rows[0]["error"] == "boom"
    logbuffer.enable_file_log("")
    logbuffer.clear()
