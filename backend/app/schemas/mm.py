"""Pydantic 스키마 — API 입출력 검증/직렬화."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# ---------- 공통 ----------
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 자재 그룹 ----------
class MaterialGroupOut(ORMModel):
    group_code: str
    name: str


# ---------- 자재 (Material) ----------
class MaterialBase(BaseModel):
    description: str = Field(..., max_length=120, description="자재 내역")
    material_type: str = Field("HAWA", max_length=4, description="자재유형(HAWA 상품 등)")
    group_code: str | None = Field(None, max_length=9)
    base_uom: str = Field("EA", max_length=3)


class MaterialCreate(MaterialBase):
    material_no: str = Field(..., max_length=18, description="자재번호(MATNR)")


class MaterialUpdate(BaseModel):
    description: str | None = Field(None, max_length=120)
    material_type: str | None = Field(None, max_length=4)
    group_code: str | None = Field(None, max_length=9)
    base_uom: str | None = Field(None, max_length=3)


class MaterialOut(MaterialBase, ORMModel):
    material_no: str
    created_at: datetime | None = None


# ---------- 재고 (Stock) ----------
class StockOut(ORMModel):
    material_no: str
    plant_id: str
    sloc_id: str
    unrestricted_qty: Decimal
    safety_stock: Decimal
    reorder_point: Decimal
    updated_at: datetime | None = None


class StockWithMaterial(StockOut):
    """재고 + 자재명 조인 결과(대시보드용)."""
    description: str | None = None
    group_code: str | None = None


# ---------- 마스터 조회 ----------
class PlantOut(ORMModel):
    plant_id: str
    name: str


class StorageLocationOut(ORMModel):
    plant_id: str
    sloc_id: str
    name: str


class MovementTypeOut(ORMModel):
    code: str
    description: str
    direction: int
