"""경영용어 사전 API. 화면의 ? 툴팁이 여기서 설명을 가져간다."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.data.glossary import GLOSSARY, as_list, categories

router = APIRouter(prefix="/api/glossary", tags=["용어 사전"])


@router.get("", summary="경영·ERP 용어 전체 목록")
def list_terms(category: str | None = Query(None, description="카테고리 필터")):
    """대시보드가 처음 한 번만 받아서 캐시하고, 모든 툴팁이 이걸 쓴다."""
    rows = as_list()
    if category:
        rows = [r for r in rows if r["category"] == category]
    return {"count": len(rows), "categories": categories(), "terms": rows}


@router.get("/{term}", summary="용어 1건 조회")
def get_term(term: str):
    item = GLOSSARY.get(term)
    if not item:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"용어 '{term}' 없음")
    return {"term": term, **item}
