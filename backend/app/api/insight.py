"""AI 해석 API — 재고·예측·발주 결과의 자연어 요약."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.services.ai_insight import generate_insight

router = APIRouter(prefix="/api/insight", tags=["AI 해석"])


@router.get("", summary="AI 자연어 요약 (발주 권장·결품 경고)")
def insight(
    provider: str | None = Query(None, description="강제 provider(gemini/ollama). 미지정 시 설정값"),
    db: Session = Depends(get_db),
):
    """KPI·재고·발주를 종합해 한국어 요약과 경고를 생성한다.
    LLM(Gemini/Ollama)이 가능하면 LLM, 아니면 규칙 기반으로 폴백한다."""
    result = generate_insight(db, provider_name=provider)
    result["configured_provider"] = settings.llm_provider
    return result
