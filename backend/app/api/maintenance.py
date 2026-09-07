"""설비 유지보수 API. 설비 마스터, 정비오더, PM 일정, 설비 KPI."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.maintenance import (
    EQUIPMENT_STATUS, ORDER_STATUS, ORDER_TYPE, Equipment,
)
from app.schemas.maintenance import (
    EquipmentCreate, EquipmentUpdate, MaintenanceOrderCreate, OrderCompleteRequest,
)
from app.services import maintenance as svc

router = APIRouter(prefix="/api/maintenance", tags=["설비 유지보수"])


@router.get("/codes", summary="상태·유형 코드표")
def codes():
    """화면 배지와 필터가 쓰는 코드-라벨 매핑."""
    return {"equipment_status": EQUIPMENT_STATUS,
            "order_type": ORDER_TYPE, "order_status": ORDER_STATUS}


@router.get("/kpi", summary="설비 KPI (가동률·PM준수율·MTTR·정비비용)")
def kpi(days: int = Query(365, ge=30, le=1095), db: Session = Depends(get_db)):
    return svc.maintenance_kpi(db, days)


@router.get("/equipment", summary="설비 목록 (정비 지연 순)")
def equipment_list(
    status_filter: str | None = Query(None, alias="status",
                                      description="RUN/CHECK/DOWN/SCRAP"),
    db: Session = Depends(get_db),
):
    return svc.list_equipment(db, status_filter)


@router.post("/equipment", status_code=status.HTTP_201_CREATED, summary="설비 등록")
def equipment_create(payload: EquipmentCreate, db: Session = Depends(get_db)):
    if db.get(Equipment, payload.equipment_no):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"설비 {payload.equipment_no} 이미 존재")
    eq = Equipment(**payload.model_dump())
    db.add(eq)
    db.commit()
    return svc.equipment_row(eq)


@router.patch("/equipment/{equipment_no}", summary="설비 수정 (상태 변경 포함)")
def equipment_update(equipment_no: str, payload: EquipmentUpdate,
                     db: Session = Depends(get_db)):
    eq = db.get(Equipment, equipment_no)
    if not eq:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"설비 {equipment_no} 없음")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(eq, k, v)
    db.commit()
    return svc.equipment_row(eq)


@router.get("/pm-schedule", summary="예방정비 일정 (지연 우선)")
def pm_schedule(horizon_days: int = Query(30, ge=1, le=365),
                db: Session = Depends(get_db)):
    """예정일이 지났으면 days_left가 음수로 나온다. 화면에서 빨간 배지가 붙는다."""
    return svc.pm_schedule(db, horizon_days)


@router.get("/orders", summary="정비오더 목록")
def order_list(
    status_filter: str | None = Query(None, alias="status",
                                      description="REQ/WIP/DONE/CANCEL"),
    equipment_no: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    return svc.list_orders(db, status_filter, equipment_no, limit)


@router.get("/orders/{order_no}", summary="정비오더 상세 (부품·비용 포함)")
def order_get(order_no: int, db: Session = Depends(get_db)):
    return svc.order_detail(db, order_no)


@router.post("/orders", status_code=status.HTTP_201_CREATED,
             summary="정비오더 등록 (CM 접수 시 설비 자동 정지)")
def order_create(payload: MaintenanceOrderCreate, db: Session = Depends(get_db)):
    return svc.create_order(db, payload)


@router.post("/orders/{order_no}/complete",
             summary="정비 완료 — 부품을 이동유형 261로 전기(재고 차감)")
def order_complete(order_no: int, payload: OrderCompleteRequest,
                   db: Session = Depends(get_db)):
    """완료하면 사용 부품이 자재문서로 남고 재고가 실제로 줄어든다.
    재고가 모자라면 409로 막혀서 장부와 실물이 어긋나지 않는다."""
    return svc.complete_order(db, order_no, payload)


@router.post("/orders/{order_no}/cancel", summary="정비오더 취소")
def order_cancel(order_no: int, db: Session = Depends(get_db)):
    return svc.cancel_order(db, order_no)
