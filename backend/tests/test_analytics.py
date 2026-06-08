"""분석 피처 행렬(data_prep) 검증 — SQLite 인메모리."""
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# analytics 패키지 경로 등록
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analytics"))

from app.core.database import Base
from app.models.mm import (
    ExtWeather, Material, MaterialDocHeader, MaterialDocItem, MovementType,
    Plant, StorageLocation,
)
from forecast.data_prep import build_features, correlation_by_material


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    s.add(Plant(plant_id="1000", name="센터"))
    s.add(StorageLocation(plant_id="1000", sloc_id="0001", name="창고"))
    s.add_all([
        Material(material_no="HEAT", description="히터", material_type="HAWA"),
        Material(material_no="FAN", description="선풍기", material_type="HAWA"),
    ])
    s.add_all([
        MovementType(code="101", description="입고", direction=1),
        MovementType(code="201", description="출고", direction=-1),
    ])
    # 5일치: 기온이 오를수록 히터 출고↓, 선풍기 출고↑
    data = [
        (date(2026, 1, 1), -5.0, 50, 5),
        (date(2026, 1, 2), 0.0, 40, 10),
        (date(2026, 1, 3), 10.0, 25, 25),
        (date(2026, 1, 4), 20.0, 12, 40),
        (date(2026, 1, 5), 28.0, 3, 55),
    ]
    for i, (d, temp, heat, fan) in enumerate(data, 1):
        s.add(ExtWeather(obs_date=d, avg_temp=temp, precip_mm=0))
        h = MaterialDocHeader(posting_date=d, source="SEED"); s.add(h); s.flush()
        s.add(MaterialDocItem(doc_no=h.doc_no, item_no=1, material_no="HEAT",
              plant_id="1000", sloc_id="0001", movement_type="201", quantity=heat))
        s.add(MaterialDocItem(doc_no=h.doc_no, item_no=2, material_no="FAN",
              plant_id="1000", sloc_id="0001", movement_type="201", quantity=fan))
        # 입고도 한 건 섞어 출고만 집계되는지 확인
        s.add(MaterialDocItem(doc_no=h.doc_no, item_no=3, material_no="HEAT",
              plant_id="1000", sloc_id="0001", movement_type="101", quantity=100))
    s.commit()
    yield s
    s.close()


def test_build_features_columns(db):
    df = build_features(db)
    for col in ["date", "material_no", "qty", "avg_temp", "is_weekend", "is_holiday"]:
        assert col in df.columns
    # 자재 2종 × 5일 = 10행 (입고는 제외)
    assert len(df) == 10


def test_issues_exclude_inbound(db):
    df = build_features(db)
    # HEAT 1/1 출고는 50 (입고 100은 집계 제외)
    row = df[(df.material_no == "HEAT") & (df.date == "2026-01-01")]
    assert float(row["qty"].iloc[0]) == 50


def test_correlation_signs(db):
    df = build_features(db)
    corr = correlation_by_material(df).set_index("material_no")
    assert corr.loc["HEAT", "corr_temp"] < -0.9   # 난방형 음의 상관
    assert corr.loc["FAN", "corr_temp"] > 0.9      # 냉방형 양의 상관
