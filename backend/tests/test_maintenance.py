"""설비 유지보수 테스트. 정비오더 흐름과 261 재고 연동을 본다.

제일 확인하고 싶은 건 두 가지다. 정비 완료가 상태만 바꾸고 끝나는 게 아니라
실제로 재고를 빼는지, 그리고 재고가 모자랄 때 완료가 거부돼서 장부와 실물이
어긋나지 않는지.
"""
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.maintenance import Equipment
from app.models.mm import (
    Material, MaterialGroup, MovementType, Plant, Stock, StorageLocation,
)


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = TestSession()
    db.add(Plant(plant_id="1000", name="물류센터"))
    db.add(StorageLocation(plant_id="1000", sloc_id="0001", name="상온 창고"))
    db.add(MaterialGroup(group_code="SAFETY", name="안전·보호구"))
    db.add_all([
        MovementType(code="101", description="입고", direction=1),
        MovementType(code="201", description="출고", direction=-1),
    ])
    db.flush()
    db.add(Material(material_no="110003", description="산업용 안전장갑",
                    material_type="HAWA", group_code="SAFETY", base_uom="EA",
                    unit_price=12000))
    db.add(Stock(material_no="110003", plant_id="1000", sloc_id="0001",
                 unrestricted_qty=10))
    db.add(Equipment(equipment_no="EQ-1001", name="전동 지게차", category="하역",
                     plant_id="1000", sloc_id="0001", pm_cycle_days=90,
                     last_pm_date=date.today() - timedelta(days=100)))
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


def test_equipment_list_and_pm_overdue(client):
    """PM 주기가 지나면 지연일수가 계산돼 나와야 한다."""
    r = client.get("/api/maintenance/equipment")
    assert r.status_code == 200
    eq = r.json()[0]
    assert eq["equipment_no"] == "EQ-1001"
    assert eq["next_pm_date"] is not None
    assert eq["overdue_days"] == 10          # 100일 전 정비 + 90일 주기


def test_pm_schedule_shows_overdue_first(client):
    rows = client.get("/api/maintenance/pm-schedule").json()
    assert rows and rows[0]["days_left"] == -10


def test_create_cm_order_stops_equipment(client):
    """고장(CM)을 접수하면 설비가 바로 고장 정지가 돼서 가동률에 반영된다."""
    r = client.post("/api/maintenance/orders", json={
        "equipment_no": "EQ-1001", "order_type": "CM", "priority": "H",
        "title": "유압 누유", "parts": [{"material_no": "110003", "quantity": 2}]})
    assert r.status_code == 201
    assert r.json()["status"] == "REQ"
    assert r.json()["part_count"] == 1

    eq = client.get("/api/maintenance/equipment").json()[0]
    assert eq["status"] == "DOWN"


def test_complete_order_posts_material_document(client):
    """완료하면 부품이 261로 전기되고 재고가 실제로 줄어야 한다."""
    order = client.post("/api/maintenance/orders", json={
        "equipment_no": "EQ-1001", "order_type": "PM", "title": "정기 점검",
        "parts": [{"material_no": "110003", "quantity": 3}]}).json()

    before = client.get("/api/stock/110003").json()
    r = client.post(f"/api/maintenance/orders/{order['order_no']}/complete",
                    json={"labor_cost": 100000})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "DONE"
    assert body["posted_doc_no"] is not None
    assert body["parts"][0]["posted_doc_no"] == body["posted_doc_no"]
    # 부품비 = 3개 × 12,000원, 총비용 = 부품비 + 인건비
    assert body["part_cost"] == 36000
    assert body["total_cost"] == 136000

    after = client.get("/api/stock/110003").json()
    assert float(after[0]["unrestricted_qty"]) == float(before[0]["unrestricted_qty"]) - 3

    # PM을 완료하면 최근 정비일이 갱신돼서 지연이 풀린다
    eq = client.get("/api/maintenance/equipment").json()[0]
    assert eq["status"] == "RUN"
    assert eq["last_pm_date"] == str(date.today())
    assert eq["overdue_days"] == 0


def test_complete_rejected_when_stock_insufficient(client):
    """재고보다 많은 부품은 못 뺀다. 완료가 409로 거부돼야 한다."""
    order = client.post("/api/maintenance/orders", json={
        "equipment_no": "EQ-1001", "order_type": "PM", "title": "대규모 교체",
        "parts": [{"material_no": "110003", "quantity": 999}]}).json()
    r = client.post(f"/api/maintenance/orders/{order['order_no']}/complete", json={})
    assert r.status_code == 409

    # 거부됐으면 오더도 재고도 그대로여야 한다. 부분 반영되면 안 된다
    assert client.get(f"/api/maintenance/orders/{order['order_no']}").json()["status"] == "REQ"
    assert float(client.get("/api/stock/110003").json()[0]["unrestricted_qty"]) == 10


def test_complete_twice_rejected(client):
    order = client.post("/api/maintenance/orders", json={
        "equipment_no": "EQ-1001", "order_type": "PM", "title": "점검"}).json()
    assert client.post(f"/api/maintenance/orders/{order['order_no']}/complete",
                       json={}).status_code == 200
    assert client.post(f"/api/maintenance/orders/{order['order_no']}/complete",
                       json={}).status_code == 409


def test_maintenance_kpi(client):
    client.post("/api/maintenance/orders", json={
        "equipment_no": "EQ-1001", "order_type": "CM", "title": "고장"})
    k = client.get("/api/maintenance/kpi").json()
    assert k["equipment_total"] == 1
    assert k["equipment_down"] == 1
    assert k["uptime_rate_pct"] == 0.0        # 1대뿐인데 고장났으니 가동률 0
    assert k["open_order_count"] == 1


def test_order_on_unknown_equipment_404(client):
    r = client.post("/api/maintenance/orders", json={
        "equipment_no": "EQ-9999", "title": "없는 설비"})
    assert r.status_code == 404
