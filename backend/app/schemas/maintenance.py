"""설비 유지보수 스키마."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EquipmentCreate(BaseModel):
    equipment_no: str = Field(..., max_length=18)
    name: str = Field(..., max_length=120)
    category: str = Field(..., max_length=20, description="하역/반송/공조/포장/전기")
    plant_id: str = Field("1000", max_length=4)
    sloc_id: str = Field("0001", max_length=4)
    manufacturer: str | None = Field(None, max_length=60)
    install_date: date | None = None
    status: str = Field("RUN", pattern="^(RUN|CHECK|DOWN|SCRAP)$")
    pm_cycle_days: int = Field(0, ge=0, description="예방정비 주기(일). 0=PM 비대상")
    last_pm_date: date | None = None


class EquipmentUpdate(BaseModel):
    name: str | None = Field(None, max_length=120)
    category: str | None = Field(None, max_length=20)
    status: str | None = Field(None, pattern="^(RUN|CHECK|DOWN|SCRAP)$")
    pm_cycle_days: int | None = Field(None, ge=0)
    last_pm_date: date | None = None


class OrderPartLine(BaseModel):
    """정비에 쓸 부품 1건 — 완료 시 이동유형 261로 재고에서 빠진다."""
    material_no: str = Field(..., max_length=18)
    quantity: Decimal = Field(..., gt=0)
    uom: str = Field("EA", max_length=3)


class MaintenanceOrderCreate(BaseModel):
    equipment_no: str = Field(..., max_length=18)
    order_type: str = Field("PM", pattern="^(PM|CM)$")
    priority: str = Field("M", pattern="^(H|M|L)$")
    title: str = Field(..., max_length=200)
    description: str | None = Field(None, max_length=500)
    requester: str | None = Field(None, max_length=40)
    request_date: date | None = Field(None, description="기본: 오늘")
    planned_date: date | None = Field(None, description="정비 예정일(지연 판정 기준)")
    parts: list[OrderPartLine] = Field(default_factory=list)


class OrderCompleteRequest(BaseModel):
    """정비 완료 처리 — 부품을 재고에서 실제로 차감한다."""
    completed_date: date | None = Field(None, description="기본: 오늘")
    labor_cost: Decimal = Field(0, ge=0, description="투입 인건비(원)")
    note: str | None = Field(None, max_length=500)


class OrderPartOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    item_no: int
    material_no: str
    description: str | None = None
    quantity: Decimal
    uom: str
    posted_doc_no: int | None = None
