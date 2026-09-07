"""운영 챗봇 API. 재고·예측·발주·설비·용어를 자연어로 묻는다."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.services.chatbot import answer, suggestions

router = APIRouter(prefix="/api/chat", tags=["운영 챗봇"])


class ChatTurn(BaseModel):
    role: str = Field(..., description="user | assistant")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list,
                                    description="이전 대화(최근 3턴만 사용)")
    provider: str | None = Field(None, description="강제 provider(ollama/gemini)")


@router.get("/suggestions", summary="예시 질문 (첫 화면용)")
def chat_suggestions(db: Session = Depends(get_db)):
    return {"provider": settings.llm_provider, "suggestions": suggestions(db)}


@router.post("", summary="챗봇 질의")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    """서버가 DB에서 조회한 수치만 컨텍스트로 넘기고 LLM이 답을 만든다.
    LLM이 없거나 실패하면 같은 데이터를 규칙 기반으로 읽어서 답한다."""
    result = answer(
        db, body.message,
        history=[t.model_dump() for t in body.history],
        provider_name=body.provider,
    )
    result["configured_provider"] = settings.llm_provider
    return result
