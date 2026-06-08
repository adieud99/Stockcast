"""분석용 피처 행렬 생성 — 출고 실적 × 외부 변수 결합.

수요예측(W6)의 입력 데이터를 만든다.
  - 출고 실적: 자재문서 항목 중 이동유형 방향 -1(출고)을 일자×자재로 집계
  - 외부 변수: ext_weather(평균기온), ext_holiday(공휴일), 요일/주말 파생

DB 세션을 받아 pandas DataFrame을 반환한다(테스트는 SQLite로 검증).
"""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mm import (
    ExtHoliday, ExtWeather, MaterialDocHeader, MaterialDocItem, MovementType,
)


def load_daily_issues(db: Session) -> pd.DataFrame:
    """일자×자재 출고량(이동유형 방향 -1) 집계."""
    stmt = (
        select(
            MaterialDocHeader.posting_date.label("date"),
            MaterialDocItem.material_no,
            MaterialDocItem.quantity,
        )
        .join(MaterialDocHeader, MaterialDocHeader.doc_no == MaterialDocItem.doc_no)
        .join(MovementType, MovementType.code == MaterialDocItem.movement_type)
        .where(MovementType.direction == -1)
    )
    rows = db.execute(stmt).all()
    if not rows:
        return pd.DataFrame(columns=["date", "material_no", "qty"])
    df = pd.DataFrame(rows, columns=["date", "material_no", "qty"])
    df["qty"] = df["qty"].astype(float)
    df["date"] = pd.to_datetime(df["date"])
    return (df.groupby(["date", "material_no"], as_index=False)["qty"].sum())


def load_weather(db: Session) -> pd.DataFrame:
    rows = db.execute(select(ExtWeather.obs_date, ExtWeather.avg_temp,
                             ExtWeather.precip_mm)).all()
    df = pd.DataFrame(rows, columns=["date", "avg_temp", "precip_mm"])
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["avg_temp"] = df["avg_temp"].astype(float)
        df["precip_mm"] = df["precip_mm"].astype(float)
    return df


def load_holidays(db: Session) -> set:
    rows = db.scalars(select(ExtHoliday.holiday_date)).all()
    return {pd.Timestamp(d) for d in rows}


def build_features(db: Session) -> pd.DataFrame:
    """출고 + 외부변수 결합 피처 행렬.

    반환 컬럼: date, material_no, qty, avg_temp, precip_mm,
              dow(요일), is_weekend, is_holiday
    """
    issues = load_daily_issues(db)
    if issues.empty:
        return issues
    weather = load_weather(db)
    holidays = load_holidays(db)

    df = issues.merge(weather, on="date", how="left")
    df["dow"] = df["date"].dt.dayofweek
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["is_holiday"] = df["date"].isin(holidays).astype(int)
    return df.sort_values(["material_no", "date"]).reset_index(drop=True)


def correlation_by_material(df: pd.DataFrame) -> pd.DataFrame:
    """자재별 기온↔출고 상관계수."""
    out = []
    for mat, g in df.groupby("material_no"):
        if g["avg_temp"].notna().sum() >= 2:
            r = g["qty"].corr(g["avg_temp"])
            out.append({"material_no": mat, "n": len(g),
                        "corr_temp": round(r, 3)})
    return pd.DataFrame(out)
