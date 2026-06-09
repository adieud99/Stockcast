"""W11 통합 테스트 — 전체 흐름 E2E 검증.

자재 등록 → 입출고(NFC) → 재고 갱신 → 수요예측 → 발주 권고 →
KPI 집계 → AI 요약 까지 하나의 시나리오로 이어서 검증한다.
시드 데이터 위에서 실제 API를 순차 호출한다.
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "db" / "seeds"))

from app.core.database import Base, get_db
from app.main import app
from seed_orm import seed_all


@pytest.fixture()
def client():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng)
    db = TS()
    seed_all(db, days=300)
    db.close()

    def override():
        d = TS()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_full_pipeline(client):
    """전체 백오피스 흐름이 끊김 없이 이어지는지 검증."""

    # 1) 자재 마스터 — 시드로 7종 존재
    mats = client.get("/api/materials").json()
    assert len(mats) == 29

    # 2) NFC 입고 → 재고 증가
    before = float(client.get("/api/stock/100001").json()[0]["unrestricted_qty"])
    r = client.post("/api/nfc/scan", json={
        "tag_uid": "04:A1:B2:C3:D4:01", "movement_type": "101", "quantity": 100})
    assert r.status_code == 201
    after_in = float(r.json()["lines"][0]["new_qty"])
    assert after_in == before + 100

    # 3) NFC 출고 → 재고 감소
    r = client.post("/api/nfc/scan", json={
        "tag_uid": "04:A1:B2:C3:D4:01", "movement_type": "201", "quantity": 40})
    after_out = float(r.json()["lines"][0]["new_qty"])
    assert after_out == after_in - 40

    # 4) 수요예측 — 난방 품목은 음의 기온계수
    fc = client.get("/api/forecast/100001?avg_temp=-5").json()
    assert fc["temp_effect_per_1deg"] < 0
    assert fc["predicted_qty"] >= 0
    assert fc["r2"] > 0.5

    # 5) 발주 권고 — 안전재고·ROP 산출
    recs = client.get("/api/reorder").json()
    assert len(recs) == 29
    assert all("safety_stock" in r and "reorder_point" in r for r in recs)

    # 6) 안전재고·ROP를 재고에 반영
    applied = client.post("/api/reorder/apply").json()
    assert applied["updated"] == 29

    # 7) KPI 집계
    kpi = client.get("/api/kpi/summary").json()
    assert kpi["sku_count"] == 29
    assert kpi["avg_turnover"] >= 0
    assert client.get("/api/kpi/turnover").json()
    assert client.get("/api/kpi/monthly-issues").json()

    # 8) AI 요약 — LLM 키 없으면 규칙 폴백
    ins = client.get("/api/insight").json()
    assert ins["source"] in ("rule", "gemini", "ollama")
    assert len(ins["summary"]) > 0


def test_screens_served(client):
    """사용자 화면(홈/대시보드/NFC/문서)이 모두 응답하는지."""
    assert client.get("/").status_code == 200
    assert client.get("/dashboard").status_code == 200
    assert client.get("/nfc").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/health").json()["status"] == "ok"


def test_stock_consistency_after_movements(client):
    """입출고 후 재고가 음수가 되지 않고 일관적인지."""
    # 과다 출고는 거부(409)되어 재고 보존
    q = float(client.get("/api/stock/100002").json()[0]["unrestricted_qty"])
    r = client.post("/api/nfc/scan", json={
        "tag_uid": "04:A1:B2:C3:D4:02", "movement_type": "201",
        "quantity": q + 99999})
    assert r.status_code == 409
    assert float(client.get("/api/stock/100002").json()[0]["unrestricted_qty"]) == q
