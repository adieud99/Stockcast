"""재고(Stock) 조회 API. (입출고에 의한 재고 변동은 W3 NFC/자재문서에서 처리)"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.mm import Material, Stock
from app.schemas.mm import StockOut, StockWithMaterial

router = APIRouter(prefix="/api/stock", tags=["재고"])


@router.get("", response_model=list[StockWithMaterial], summary="재고 현황 목록")
def list_stock(
    plant_id: str | None = Query(None),
    below_rop: bool = Query(False, description="재주문점 이하만 보기(발주 필요 품목)"),
    db: Session = Depends(get_db),
):
    stmt = select(Stock, Material).join(Material, Stock.material_no == Material.material_no)
    if plant_id:
        stmt = stmt.where(Stock.plant_id == plant_id)
    if below_rop:
        stmt = stmt.where(Stock.unrestricted_qty <= Stock.reorder_point)
    rows = db.execute(stmt.order_by(Stock.material_no)).all()
    result = []
    for stock, material in rows:
        item = StockWithMaterial.model_validate(stock)
        item.description = material.description
        item.group_code = material.group_code
        result.append(item)
    return result


@router.get("/{material_no}", response_model=list[StockOut],
            summary="자재별 재고 조회(저장위치별)")
def get_stock(material_no: str, db: Session = Depends(get_db)):
    rows = db.scalars(select(Stock).where(Stock.material_no == material_no)).all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"자재 {material_no} 재고 없음")
    return rows
