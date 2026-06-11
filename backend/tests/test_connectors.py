"""실 공공데이터 커넥터 파서·업서트 QA.

네트워크 없이 합성 응답으로 파싱/중복처리/실데이터 시드를 검증한다.
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

BACKEND = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(BACKEND), str(BACKEND.parent / "db" / "seeds")]
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.core.database import Base, engine, SessionLocal  # noqa: E402
import app.models.mm  # noqa: E402,F401
from app.models.mm import ExtHoliday, ExtWeather  # noqa: E402
from app.services.external import upsert_holidays  # noqa: E402
from app.services.nara import parse_bid_response  # noqa: E402
from app.services.pps import parse_mas_response  # noqa: E402
from app.services.kosis import parse_kosis_response  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.create_all(engine)
    s = SessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(engine)


def test_nara_bid_parse_and_skip_empty():
    payload = {"response": {"body": {"items": {"item": [
        {"bidNtceNo": "R26BK01", "bidNtceOrd": "00", "bidNtceNm": "제설제 구매",
         "ntceInsttNm": "○○시청", "presmptPrc": "15000000",
         "bidNtceDt": "2026-06-05 10:00:00"},
        {"bidNtceNo": "", "bidNtceNm": "공번호"},  # bid_no 없으면 제외
    ]}}}}
    rows = parse_bid_response(payload)
    assert len(rows) == 1
    assert rows[0]["bid_no"] == "R26BK01"
    assert float(rows[0]["est_price"]) == 15000000
    assert rows[0]["notice_date"] == date(2026, 6, 5)


def test_nara_items_as_list_and_comma_price():
    payload = {"response": {"body": {"items": [
        {"bidNtceNo": "X1", "bidNtceNm": "안전화", "presmptPrc": "1,200,000"},
    ]}}}
    rows = parse_bid_response(payload)
    assert len(rows) == 1 and float(rows[0]["est_price"]) == 1200000


def test_pps_mas_parse_skips_no_price():
    payload = {"response": {"body": {"items": [
        {"prdctSpecNm": "LED보안등, 50W", "cntrctCorpNm": "(주)위드",
         "cntrctPrceAmt": "230000", "prdctUnit": "개", "dlvrTmlmtDaynum": "30"},
        {"prdctSpecNm": "단가없음", "cntrctPrceAmt": ""},  # 단가 없으면 제외
    ]}}}
    rows = parse_mas_response(payload)
    assert len(rows) == 1
    assert float(rows[0]["contract_price"]) == 230000
    assert rows[0]["delivery_days"] == 30


def test_kosis_parse_and_error_dict():
    sample = [
        {"PRD_DE": "202505", "DT": "108.7", "C1_NM": "의복", "UNIT_NM": "2020=100"},
        {"PRD_DE": "bad", "DT": "9"},  # 잘못된 기간 제외
    ]
    rows = parse_kosis_response(sample)
    assert len(rows) == 1 and rows[0]["period"] == "202505"
    # 오류 응답(dict)은 빈 리스트
    assert parse_kosis_response({"err": "030", "errMsg": "인증키오류"}) == []


def test_holiday_dedup_same_date(db):
    # 같은 날짜(어린이날·부처님오신날)는 한 건으로 합쳐져야 함
    rows = [
        {"holiday_date": date(2025, 5, 5), "name": "어린이날", "is_holiday": True},
        {"holiday_date": date(2025, 5, 5), "name": "부처님오신날", "is_holiday": True},
        {"holiday_date": date(2025, 1, 1), "name": "신정", "is_holiday": True},
    ]
    n = upsert_holidays(db, rows)
    assert n == 2
    total = db.scalar(select(func.count()).select_from(ExtHoliday))
    assert total == 2
    h = db.get(ExtHoliday, date(2025, 5, 5))
    assert "어린이날" in h.name and "부처님오신날" in h.name


def test_seed_uses_real_weather(db):
    # DB에 실제 날씨를 미리 넣고 use_real_weather=True면 합성 날씨를 만들지 않는다
    from seed_orm import seed_all
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=29)
    for i in range(30):
        d = start + timedelta(days=i)
        db.add(ExtWeather(obs_date=d, region_code="108", avg_temp=10.0 + i,
                          min_temp=5.0, max_temp=15.0, precip_mm=0.0))
    db.commit()
    before = db.scalar(select(func.count()).select_from(ExtWeather))
    seed_all(db, days=30, use_real_weather=True)
    after = db.scalar(select(func.count()).select_from(ExtWeather))
    assert before == after == 30  # 실데이터 모드는 날씨를 추가 생성하지 않음
