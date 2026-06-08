"""입출고(자재문서) / NFC 스캔 스키마."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class GoodsMovementLine(BaseModel):
    """자재문서 항목 1건."""
    material_no: str = Field(..., max_length=18)
    plant_id: str = Field("1000", max_length=4)
    sloc_id: str = Field("0001", max_length=4)
    movement_type: str = Field(..., max_length=3, description="이동유형(101 입고/201 출고)")
    quantity: Decimal = Field(..., gt=0)
    uom: str = Field("EA", max_length=3)


class GoodsMovementCreate(BaseModel):
    """자재문서(헤더+항목) 생성 요청."""
    posting_date: date | None = Field(None, description="전기일(기본: 오늘)")
    source: str = Field("MANUAL", max_length=10)
    lines: list[GoodsMovementLine] = Field(..., min_length=1)


class NfcScanRequest(BaseModel):
    """NFC 단일 스캔 입출고 요청.

    태그 UID로 자재/저장위치를 해석하므로 수량과 이동유형만 받는다.
    """
    tag_uid: str = Field(..., max_length=64)
    movement_type: str = Field(..., max_length=3, description="101 입고 / 201 출고")
    quantity: Decimal = Field(1, gt=0)
    source: str = Field("NFC", max_length=10)


class MovementResultLine(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    material_no: str
    movement_type: str
    quantity: Decimal
    new_qty: Decimal = Field(..., description="처리 후 가용재고")


class MovementResult(BaseModel):
    doc_no: int
    posting_date: date
    source: str
    created_at: datetime | None = None
    lines: list[MovementResultLine]
