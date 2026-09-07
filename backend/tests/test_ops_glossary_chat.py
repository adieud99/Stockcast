"""운영 관리, 용어 사전, 챗봇 테스트.

세 기능이 지켜야 할 것들을 고정해둔다. 용어 사전은 화면이 아니라 백엔드 한
곳에서 나와야 하고, 정합성 점검은 틀렸다는 것만이 아니라 뭘 해야 하는지까지
줘야 하고, 챗봇은 LLM 없이도 실제 DB 수치로 답해야 한다.
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.logbuffer import clear
from app.data.glossary import GLOSSARY
from app.main import app
from app.models.maintenance import Equipment
from app.models.mm import (
    Material, MaterialDocHeader, MaterialDocItem, MaterialGroup, MovementType,
    Plant, Stock, StorageLocation,
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
    db.add(MaterialGroup(group_code="DEICE", name="제설·방재"))
    db.add_all([
        MovementType(code="101", description="입고", direction=1),
        MovementType(code="201", description="출고", direction=-1),
    ])
    db.flush()
    db.add(Material(material_no="100001", description="친환경 제설제 25kg",
                    material_type="HAWA", group_code="DEICE", unit_price=15000))
    # 입고 100에서 출고 40을 빼면 재고 60. C01이 통과하는 상태로 맞춰둔다
    h = MaterialDocHeader(posting_date=date.today(), source="TEST")
    db.add(h)
    db.flush()
    db.add(MaterialDocItem(doc_no=h.doc_no, item_no=1, material_no="100001",
                           plant_id="1000", sloc_id="0001",
                           movement_type="101", quantity=100))
    db.add(MaterialDocItem(doc_no=h.doc_no, item_no=2, material_no="100001",
                           plant_id="1000", sloc_id="0001",
                           movement_type="201", quantity=40))
    db.add(Stock(material_no="100001", plant_id="1000", sloc_id="0001",
                 unrestricted_qty=60, safety_stock=10, reorder_point=25))
    db.add(Equipment(equipment_no="EQ-1001", name="지게차", category="하역",
                     plant_id="1000", sloc_id="0001", pm_cycle_days=0))
    db.commit()
    db.close()

    def override_get_db():
        d = TestSession()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = override_get_db
    clear()
    yield TestClient(app)
    app.dependency_overrides.clear()


# ── 용어 사전 ───────────────────────────────────────────────────

def test_glossary_list(client):
    r = client.get("/api/glossary")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(GLOSSARY)
    assert "재고" in body["categories"]
    assert all({"term", "short", "detail", "category"} <= set(t) for t in body["terms"])


def test_glossary_filter_and_detail(client):
    rows = client.get("/api/glossary?category=설비").json()["terms"]
    assert rows and all(t["category"] == "설비" for t in rows)

    r = client.get("/api/glossary/안전재고")
    assert r.status_code == 200
    assert "Z" in r.json()["formula"]          # 계산식이 근거로 함께 온다
    assert client.get("/api/glossary/없는용어").status_code == 404


# ── 운영 관리 ───────────────────────────────────────────────────

def test_ops_health(client):
    body = client.get("/api/ops/health").json()
    assert body["status"] in ("healthy", "degraded", "down")
    assert body["components"]["database"]["ok"] is True
    # Odoo 미설정은 '장애'가 아니라 '미설정'으로 구분된다
    assert body["components"]["odoo"]["configured"] is False
    assert "python" in body["runtime"]


def test_ops_integrity_passes_on_consistent_data(client):
    body = client.get("/api/ops/integrity").json()
    codes = {c["code"]: c for c in body["checks"]}
    assert body["total"] == 9
    assert codes["C01"]["passed"] is True      # 문서 합계(100−40=60) = 재고 60
    assert codes["C02"]["passed"] is True
    assert codes["C03"]["passed"] is True
    assert body["critical"] == 0
    # 통과 못 한 점검은 조치 문구가 반드시 있어야 한다
    assert all(c["action"] for c in body["checks"] if not c["passed"])


def test_ops_integrity_detects_stock_mismatch(client):
    """이동 없이 재고를 바꾸면 C01이 잡아내야 한다."""
    from app.main import app as _app
    gen = _app.dependency_overrides[get_db]()
    db = next(gen)
    db.get(Stock, ("100001", "1000", "0001")).unrestricted_qty = 999
    db.commit()
    db.close()

    codes = {c["code"]: c for c in client.get("/api/ops/integrity").json()["checks"]}
    assert codes["C01"]["passed"] is False
    assert codes["C01"]["bad_count"] == 1
    assert codes["C01"]["samples"][0]["expected"] == 60
    assert codes["C01"]["samples"][0]["actual"] == 999


def test_ops_logs_capture_requests(client):
    client.get("/api/glossary")
    client.get("/api/materials/999999")        # 404를 하나 만든다
    body = client.get("/api/ops/logs").json()
    paths = [r["path"] for r in body["records"]]
    assert "/api/glossary" in paths

    errs = client.get("/api/ops/logs?level=error").json()["records"]
    assert errs and all(r["status_code"] >= 400 for r in errs)
    assert client.post("/api/ops/logs/clear").json()["cleared"] > 0


def test_ops_stats(client):
    body = client.get("/api/ops/stats").json()
    tables = {t["table"]: t["rows"] for t in body["tables"]}
    assert tables["material"] == 1
    assert tables["material_doc_item"] == 2
    assert tables["equipment"] == 1


# ── 챗봇 ────────────────────────────────────────────────────────

def test_chat_intent_glossary(client):
    """용어 질문은 사전에서 답한다. 툴팁이 쓰는 것과 같은 사전이다."""
    r = client.post("/api/chat", json={"message": "안전재고가 무슨 뜻이야?"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "glossary"
    assert body["source"] == "rule"             # 테스트 환경에는 LLM 키가 없다
    assert "안전재고" in body["answer"]
    assert "안전재고" in body["terms"]


def test_chat_intent_stock_uses_real_numbers(client):
    """품목을 물으면 DB의 실제 수치가 답에 들어가야 한다. 환각 방지."""
    body = client.post("/api/chat", json={"message": "제설제 재고 얼마나 남았어"}).json()
    assert body["intent"] == "stock"
    assert "60" in body["answer"]


def test_chat_intent_maintenance(client):
    body = client.post("/api/chat", json={"message": "설비 가동률 어때?"}).json()
    assert body["intent"] == "maintenance"
    assert "가동률" in body["answer"]


def test_chat_intent_reorder(client):
    body = client.post("/api/chat", json={"message": "지금 발주해야 할 품목 알려줘"}).json()
    assert body["intent"] == "reorder"
    assert body["answer"]


def test_chat_default_intent_and_empty(client):
    body = client.post("/api/chat", json={"message": "안녕"}).json()
    assert body["intent"] == "kpi"              # 매칭되는 의도가 없으면 전체 현황
    assert client.post("/api/chat", json={"message": ""}).status_code == 422


def test_chat_suggestions(client):
    body = client.get("/api/chat/suggestions").json()
    assert 1 <= len(body["suggestions"]) <= 4
