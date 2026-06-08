"""백엔드 API 통합 테스트 — SQLite 인메모리로 실제 구동 검증.

실DB(PostgreSQL) 없이도 API 동작을 빠르게 검증한다.
운영은 PostgreSQL이지만, ORM/스키마/엔드포인트 로직 검증에는 SQLite로 충분하다.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.mm import (
    Material, MaterialGroup, Plant, Stock, StorageLocation,
)


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # 마스터/재고 시드
    db = TestSession()
    db.add(Plant(plant_id="1000", name="서울 본사 물류센터"))
    db.add(StorageLocation(plant_id="1000", sloc_id="0001", name="상온 창고"))
    db.add(MaterialGroup(group_code="HEAT", name="난방용품"))
    db.add(Material(material_no="100001", description="전기 히터",
                    material_type="HAWA", group_code="HEAT", base_uom="EA"))
    db.add(Stock(material_no="100001", plant_id="1000", sloc_id="0001",
                 unrestricted_qty=50, safety_stock=20, reorder_point=30))
    db.commit()
    db.close()

    def override_get_db():
        d = TestSession()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_list_materials(client):
    r = client.get("/api/materials")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["material_no"] == "100001"


def test_get_material_404(client):
    assert client.get("/api/materials/999999").status_code == 404


def test_create_material(client):
    payload = {"material_no": "100002", "description": "온수 매트",
               "material_type": "HAWA", "group_code": "HEAT", "base_uom": "EA"}
    r = client.post("/api/materials", json=payload)
    assert r.status_code == 201
    assert r.json()["description"] == "온수 매트"
    assert client.get("/api/materials/100002").status_code == 200


def test_create_duplicate_material(client):
    payload = {"material_no": "100001", "description": "중복"}
    assert client.post("/api/materials", json=payload).status_code == 409


def test_create_material_bad_group(client):
    payload = {"material_no": "100003", "description": "x", "group_code": "NONE"}
    assert client.post("/api/materials", json=payload).status_code == 400


def test_update_material(client):
    r = client.patch("/api/materials/100001", json={"description": "전기 히터(개정)"})
    assert r.status_code == 200
    assert r.json()["description"] == "전기 히터(개정)"


def test_delete_material(client):
    payload = {"material_no": "200001", "description": "선풍기"}
    client.post("/api/materials", json=payload)
    assert client.delete("/api/materials/200001").status_code == 204
    assert client.get("/api/materials/200001").status_code == 404


def test_list_stock(client):
    r = client.get("/api/stock")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["material_no"] == "100001"
    assert body[0]["description"] == "전기 히터"


def test_stock_below_rop(client):
    # 100001: qty=50, rop=30 → below_rop=true 면 제외
    assert len(client.get("/api/stock?below_rop=true").json()) == 0
    assert len(client.get("/api/stock").json()) == 1
