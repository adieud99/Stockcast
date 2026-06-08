"""외부 데이터(날씨·공휴일) 조회 및 수집 트리거 API."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.mm import ExtHoliday, ExtWeather
from app.services.external import collect_holidays, collect_weather

router = APIRouter(prefix="/api/external", tags=["외부 데이터"])


@router.get("/weather", summary="날씨 데이터 조회")
def list_weather(
    start: date | None = Query(None, description="조회 시작일 (예: 2025-01-01)"),
    end: date | None = Query(None, description="조회 종료일 (예: 2025-01-31)"),
    db: Session = Depends(get_db),
):
    stmt = select(ExtWeather)
    if start:
        stmt = stmt.where(ExtWeather.obs_date >= start)
    if end:
        stmt = stmt.where(ExtWeather.obs_date <= end)
    rows = db.scalars(stmt.order_by(ExtWeather.obs_date)).all()
    return [{"obs_date": r.obs_date, "avg_temp": r.avg_temp,
             "min_temp": r.min_temp, "max_temp": r.max_temp,
             "precip_mm": r.precip_mm} for r in rows]


@router.get("/holidays", summary="공휴일 조회")
def list_holidays(year: int | None = Query(None), db: Session = Depends(get_db)):
    stmt = select(ExtHoliday)
    if year:
        stmt = stmt.where(ExtHoliday.holiday_date >= date(year, 1, 1),
                          ExtHoliday.holiday_date <= date(year, 12, 31))
    rows = db.scalars(stmt.order_by(ExtHoliday.holiday_date)).all()
    return [{"holiday_date": r.holiday_date, "name": r.name,
             "is_holiday": r.is_holiday} for r in rows]


@router.post("/collect/weather", summary="날씨 수집 실행")
def trigger_weather(
    start: date = Query(..., description="수집 시작일 (예: 2025-01-01)"),
    end: date = Query(..., description="수집 종료일 (예: 2025-01-31)"),
    db: Session = Depends(get_db),
):
    return collect_weather(db, start, end)


@router.post("/collect/holidays", summary="공휴일 수집 실행")
def trigger_holidays(
    year: int = Query(..., description="수집 연도 (예: 2025)"),
    db: Session = Depends(get_db),
):
    return collect_holidays(db, year)
