"""로그인·권한 테스트 (FR-11).

conftest 의 관리자 대역을 걷어내고 실제 토큰으로 본다.
계정은 conftest 가 고정한다: admin/admin-pw, viewer/viewer-pw.
"""
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import auth
from app.core.database import Base, get_db
from app.main import app
from app.models.mm import Material, MaterialGroup, Plant, Stock, StorageLocation

pytestmark = pytest.mark.real_auth


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
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
    auth._failures.clear()
    yield TestClient(app)
    app.dependency_overrides.clear()
    auth._failures.clear()


def _token(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_returns_role(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pw"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    r = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer-pw"})
    assert r.json()["role"] == "viewer"


def test_wrong_password_and_unknown_user(client):
    for u, p in (("admin", "nope"), ("ghost", "admin-pw")):
        r = client.post("/api/auth/login", json={"username": u, "password": p})
        assert r.status_code == 401


def test_api_requires_token(client):
    r = client.get("/api/materials")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_tampered_and_expired_tokens_rejected(client):
    token = _token(client, "admin", "admin-pw")
    body, sig = token.split(".")
    forged = auth._b64(b'{"sub":"admin","role":"admin","exp":9999999999}')
    assert client.get("/api/materials", headers=_h(f"{forged}.{sig}")).status_code == 401

    old, _ = auth.issue_token("admin", "admin", now=time.time() - 3 * 24 * 3600)
    assert client.get("/api/materials", headers=_h(old)).status_code == 401
    assert client.get("/api/materials", headers=_h("garbage")).status_code == 401


def test_viewer_reads_but_cannot_write(client):
    h = _h(_token(client, "viewer", "viewer-pw"))
    assert client.get("/api/materials", headers=h).status_code == 200
    r = client.post("/api/materials", headers=h,
                    json={"material_no": "100002", "description": "온수 매트"})
    assert r.status_code == 403
    assert client.delete("/api/materials/100001", headers=h).status_code == 403


def test_viewer_can_use_chatbot(client):
    h = _h(_token(client, "viewer", "viewer-pw"))
    r = client.post("/api/chat", headers=h, json={"message": "발주해야 할 품목 알려줘"})
    assert r.status_code == 200


def test_admin_can_write(client):
    h = _h(_token(client, "admin", "admin-pw"))
    r = client.post("/api/materials", headers=h,
                    json={"material_no": "100002", "description": "온수 매트",
                          "material_type": "HAWA", "group_code": "HEAT", "base_uom": "EA"})
    assert r.status_code == 201


def test_disabled_account_invalidates_issued_token(client, monkeypatch):
    token = _token(client, "viewer", "viewer-pw")
    monkeypatch.setattr(auth.settings, "auth_viewer_password", "")
    assert client.get("/api/materials", headers=_h(token)).status_code == 401
    r = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer-pw"})
    assert r.status_code == 401


def test_login_throttled_after_repeated_failures(client):
    for _ in range(auth.MAX_FAILURES):
        client.post("/api/auth/login", json={"username": "admin", "password": "x"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin-pw"})
    assert r.status_code == 429


def test_health_is_public_but_minimal(client):
    r = client.get("/api/ops/health")
    assert r.status_code == 200
    assert set(r.json()) == {"status"}
    full = client.get("/api/ops/health", headers=_h(_token(client, "viewer", "viewer-pw"))).json()
    assert "components" in full


def test_pages_and_liveness_are_public(client):
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200


def test_me(client):
    h = _h(_token(client, "viewer", "viewer-pw"))
    assert client.get("/api/auth/me", headers=h).json()["role"] == "viewer"
