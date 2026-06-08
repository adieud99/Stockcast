"""NFC 입출고 / 자재문서 전기 테스트 (SQLite 인메모리)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.mm import (
    Material, MaterialGroup, MovementType, NfcTag, Plant, Stock, StorageLocation,
)


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TS = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TS()
    db.add(Plant(plant_id="1000", name="센터"))
    db.add(StorageLocation(plant_id="1000", sloc_id="0001", name="창고"))
    db.add(MaterialGroup(group_code="HEAT", name="난방"))
    db.add(Material(material_no="100001", description="전기 히터",
                    material_type="HAWA", group_code="HEAT"))
    db.add(Stock(material_no="100001", plant_id="1000", sloc_id="0001",
                 unrestricted_qty=50))
    db.add_all([
        MovementType(code="101", description="입고", direction=1),
        MovementType(code="201", description="출고", direction=-1),
    ])
    db.add(NfcTag(tag_uid="04:A1:B2:C3:D4:01", material_no="100001",
                  plant_id="1000", sloc_id="0001"))
    db.commit()
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


def _qty(client):
    return client.get("/api/stock/100001").json()[0]["unrestricted_qty"]


def test_nfc_inbound_increases_stock(client):
    r = client.post("/api/nfc/scan", json={
        "tag_uid": "04:A1:B2:C3:D4:01", "movement_type": "101", "quantity": 30})
    assert r.status_code == 201
    assert float(r.json()["lines"][0]["new_qty"]) == 80
    assert float(_qty(client)) == 80


def test_nfc_outbound_decreases_stock(client):
    r = client.post("/api/nfc/scan", json={
        "tag_uid": "04:A1:B2:C3:D4:01", "movement_type": "201", "quantity": 20})
    assert r.status_code == 201
    assert float(r.json()["lines"][0]["new_qty"]) == 30
    assert float(_qty(client)) == 30


def test_nfc_outbound_insufficient_stock(client):
    r = client.post("/api/nfc/scan", json={
        "tag_uid": "04:A1:B2:C3:D4:01", "movement_type": "201", "quantity": 999})
    assert r.status_code == 409
    assert float(_qty(client)) == 50  # 변동 없음


def test_nfc_unknown_tag(client):
    r = client.post("/api/nfc/scan", json={
        "tag_uid": "UNKNOWN", "movement_type": "101", "quantity": 1})
    assert r.status_code == 404


def test_manual_multiline_movement(client):
    r = client.post("/api/movements", json={
        "source": "MANUAL",
        "lines": [
            {"material_no": "100001", "plant_id": "1000", "sloc_id": "0001",
             "movement_type": "101", "quantity": 10},
            {"material_no": "100001", "plant_id": "1000", "sloc_id": "0001",
             "movement_type": "201", "quantity": 5},
        ]})
    assert r.status_code == 201
    assert len(r.json()["lines"]) == 2
    assert float(_qty(client)) == 55  # 50 +10 -5


def test_tags_list(client):
    r = client.get("/api/nfc/tags")
    assert r.status_code == 200 and len(r.json()) == 1
