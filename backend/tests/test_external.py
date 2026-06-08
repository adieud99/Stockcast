"""외부 데이터 파싱/적재 테스트 — 실제 공공 API 응답 구조 기준."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.mm import ExtHoliday, ExtWeather
from app.services.external import (
    parse_holiday_response, parse_kma_response, upsert_holidays, upsert_weather,
)

# 기상청 ASOS 일자료 응답(축약) — 실제 구조
KMA_SAMPLE = {
    "response": {"body": {"items": {"item": [
        {"tm": "2026-01-15", "stnId": "108", "avgTa": "-3.2",
         "minTa": "-8.1", "maxTa": "1.4", "sumRn": "0.0"},
        {"tm": "2026-07-20", "stnId": "108", "avgTa": "28.5",
         "minTa": "24.0", "maxTa": "33.1", "sumRn": "12.5"},
    ]}}}
}

# 특일정보 응답(축약) — 실제 구조
HOLIDAY_SAMPLE = {
    "response": {"body": {"items": {"item": [
        {"locdate": 20260101, "dateName": "1월1일", "isHoliday": "Y"},
        {"locdate": 20260301, "dateName": "삼일절", "isHoliday": "Y"},
    ]}}}
}


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_parse_kma():
    rows = parse_kma_response(KMA_SAMPLE)
    assert len(rows) == 2
    assert str(rows[0]["obs_date"]) == "2026-01-15"
    assert float(rows[0]["avg_temp"]) == -3.2
    assert float(rows[1]["precip_mm"]) == 12.5


def test_parse_kma_single_item_dict():
    # 항목이 1건이면 공공 API가 dict로 반환하는 경우 처리
    single = {"response": {"body": {"items": {"item":
              {"tm": "2026-02-01", "stnId": "108", "avgTa": "0.5"}}}}}
    rows = parse_kma_response(single)
    assert len(rows) == 1 and float(rows[0]["avg_temp"]) == 0.5


def test_parse_kma_empty():
    assert parse_kma_response({}) == []


def test_parse_holiday():
    rows = parse_holiday_response(HOLIDAY_SAMPLE)
    assert len(rows) == 2
    assert str(rows[0]["holiday_date"]) == "2026-01-01"
    assert rows[1]["name"] == "삼일절"
    assert rows[0]["is_holiday"] is True


def test_upsert_weather_idempotent(db):
    rows = parse_kma_response(KMA_SAMPLE)
    assert upsert_weather(db, rows) == 2
    upsert_weather(db, rows)  # 재수집해도 중복 없음
    assert db.query(ExtWeather).count() == 2


def test_upsert_holidays_idempotent(db):
    rows = parse_holiday_response(HOLIDAY_SAMPLE)
    upsert_holidays(db, rows)
    upsert_holidays(db, rows)
    assert db.query(ExtHoliday).count() == 2
