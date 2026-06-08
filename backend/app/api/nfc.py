"""NFC 입출고 + 자재문서 전기 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.mm import NfcTag
from app.schemas.movement import (
    GoodsMovementCreate, MovementResult, NfcScanRequest,
)
from app.services.inventory import post_goods_movement, post_nfc_scan

router = APIRouter(prefix="/api", tags=["입출고 / NFC"])


@router.post("/nfc/scan", response_model=MovementResult,
             status_code=status.HTTP_201_CREATED,
             summary="NFC 스캔 입출고 (태그 1건)")
def nfc_scan(scan: NfcScanRequest, db: Session = Depends(get_db)):
    """NFC 태그 UID를 해석해 입고(101)/출고(201)를 자동 기록하고 재고를 갱신한다."""
    return post_nfc_scan(db, scan)


@router.post("/movements", response_model=MovementResult,
             status_code=status.HTTP_201_CREATED,
             summary="자재문서 전기 (수기/다건)")
def create_movement(payload: GoodsMovementCreate, db: Session = Depends(get_db)):
    """수기 입력 또는 다건 입출고를 자재문서로 전기한다."""
    return post_goods_movement(db, payload)


@router.get("/nfc/tags", tags=["입출고 / NFC"], summary="등록된 NFC 태그 목록")
def list_tags(db: Session = Depends(get_db)):
    rows = db.scalars(select(NfcTag).order_by(NfcTag.tag_uid)).all()
    return [{"tag_uid": t.tag_uid, "material_no": t.material_no,
             "plant_id": t.plant_id, "sloc_id": t.sloc_id} for t in rows]
