"""AI 해석 테스트 — 규칙 폴백 + provider 팩토리 (네트워크 불필요)."""
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
from app.services.ai_insight import gather_context, rule_based_summary
from app.services.llm import GeminiProvider, OllamaProvider, get_provider
from seed_orm import seed_all


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False},
                        poolclass=StaticPool)
    Base.metadata.create_all(eng)
    TS = sessionmaker(bind=eng)
    s = TS()
    seed_all(s, days=120)
    yield s
    s.close()


@pytest.fixture()
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_provider_factory():
    assert isinstance(get_provider("gemini"), GeminiProvider)
    assert isinstance(get_provider("ollama"), OllamaProvider)
    assert get_provider("gemini").name == "gemini"


def test_gemini_unavailable_without_key():
    # 키 미설정 → available False
    assert GeminiProvider().available() is False


def test_rule_based_summary(db):
    ctx = gather_context(db)
    out = rule_based_summary(ctx)
    assert out["source"] == "rule"
    assert "품목" in out["summary"]
    assert isinstance(out["alerts"], list)


def test_insight_endpoint_falls_back(client):
    # 키 없으므로 규칙 폴백으로 200 응답
    r = client.get("/api/insight")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in ("rule", "gemini", "ollama")
    assert "summary" in body and len(body["summary"]) > 0
