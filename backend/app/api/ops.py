"""운영자용 시스템 관리 API. 헬스체크, 로그, 데이터 정합성.

운영자가 SSH 없이 브라우저에서 상태를 확인하는 창구다.
/api/ops/health는 배포 후 확인과 cron 이 폴링해야 해서 로그인 없이 열어뒀다.
대신 로그인하지 않은 요청에는 판정(status)만 준다. 나머지는 로그인이 필요하다.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import optional_user
from app.core.database import get_db
from app.core.logbuffer import MAX_RECORDS, clear, get_records
from app.services import ops as svc

router = APIRouter(prefix="/api/ops", tags=["운영 관리"])
public_router = APIRouter(prefix="/api/ops", tags=["운영 관리"])


@public_router.get("/health", summary="시스템 상태 점검 (DB·Odoo·LLM·리소스)")
def health(db: Session = Depends(get_db), user: dict | None = Depends(optional_user)):
    """healthy(정상), degraded(Odoo 끊김), down(DB 불가) 셋 중 하나를 돌려준다.

    로그인 안 한 요청에는 판정만 준다. 구성요소·버전·자원 사용량은 공격자에게도
    쓸모 있는 정보라서다."""
    result = svc.health(db)
    return result if user else {"status": result["status"]}


@router.get("/stats", summary="테이블별 적재 현황·데이터 최신성")
def stats(db: Session = Depends(get_db)):
    return svc.table_stats(db)


@router.get("/integrity", summary="데이터 정합성 점검 (9개 항목)")
def integrity(db: Session = Depends(get_db)):
    """자재문서 합계=재고, 음수재고, 고아 참조, PM 지연 등을 한 번에 본다."""
    return svc.integrity_check(db)


@router.get("/logs", summary="최근 요청 로그 (메모리 링버퍼)")
def logs(
    limit: int = Query(100, ge=1, le=MAX_RECORDS),
    level: str | None = Query(None, description="error=4xx/5xx만, slow=느린 요청만"),
    path: str | None = Query(None, description="경로 부분 일치 필터"),
):
    return {"capacity": MAX_RECORDS,
            "records": get_records(limit=limit, level=level, path_contains=path)}


@router.post("/logs/clear", summary="요청 로그 비우기")
def logs_clear():
    return {"cleared": clear()}
