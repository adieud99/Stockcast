"""KPI 집계 API 테스트 (시드 적재 후)."""
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
    seed_all(db, days=200)
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


def test_summary(client):
    s = client.get("/api/kpi/summary").json()
    assert s["sku_count"] == 30
    assert s["total_stock_qty"] > 0
    assert s["avg_turnover"] >= 0
    assert 0 <= s["stockout_rate_pct"] <= 100


def test_turnover(client):
    rows = client.get("/api/kpi/turnover").json()
    assert len(rows) == 30
    assert all("turnover" in r for r in rows)


def test_stock_by_group(client):
    rows = client.get("/api/kpi/stock-by-group").json()
    groups = {r["group"] for r in rows}
    assert "제설·방재" in groups and "안전·보호구" in groups


def test_monthly_issues(client):
    rows = client.get("/api/kpi/monthly-issues").json()
    assert len(rows) >= 1
    assert all("month" in r and "issued" in r for r in rows)
