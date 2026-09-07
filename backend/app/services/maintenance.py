"""설비 유지보수 서비스. 정비오더 전기, PM 스케줄, 설비 KPI를 다룬다.

정비오더 완료는 상태만 바뀌는 게 아니라 재고를 소비하는 사건이다. 그래서
완료 처리에서 기존 MM 전기 로직(post_goods_movement)을 그대로 재사용해
이동유형 261로 자재문서를 남긴다. 이렇게 하면 정비 부품이 장부 없이 사라지지
않고 기존 감사추적과 재고 집계에 자동으로 들어간다.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.maintenance import (
    Equipment, MaintenanceOrder, MaintenanceOrderPart,
)
from app.models.mm import Material, MovementType
from app.schemas.maintenance import MaintenanceOrderCreate, OrderCompleteRequest
from app.schemas.movement import GoodsMovementCreate, GoodsMovementLine
from app.services.inventory import post_goods_movement

# 정비오더 소비 이동유형 — SAP BWART 261(오더에 대한 출고)
MVT_MAINTENANCE_ISSUE = "261"


def ensure_movement_type(db: Session) -> None:
    """261 이동유형이 없으면 만든다. 기존 DB에 이 모듈을 나중에 얹는 경우 대비."""
    if not db.get(MovementType, MVT_MAINTENANCE_ISSUE):
        db.add(MovementType(code=MVT_MAINTENANCE_ISSUE,
                            description="출고 (정비오더 소비)", direction=-1))
        db.commit()


# ── 조회 ────────────────────────────────────────────────────────

def _pm_due_date(eq: Equipment) -> date | None:
    """다음 예방정비 예정일. PM 주기가 없거나 이력이 없으면 None."""
    if not eq.pm_cycle_days or not eq.last_pm_date:
        return None
    return eq.last_pm_date + timedelta(days=eq.pm_cycle_days)


def equipment_row(eq: Equipment, today: date | None = None) -> dict:
    """설비 하나를 화면용 dict로 만든다. 다음 정비일과 지연일수는 여기서 계산."""
    today = today or date.today()
    due = _pm_due_date(eq)
    overdue = (today - due).days if due and due < today else 0
    return {
        "equipment_no": eq.equipment_no,
        "name": eq.name,
        "category": eq.category,
        "plant_id": eq.plant_id,
        "sloc_id": eq.sloc_id,
        "manufacturer": eq.manufacturer,
        "install_date": eq.install_date,
        "status": eq.status,
        "pm_cycle_days": eq.pm_cycle_days,
        "last_pm_date": eq.last_pm_date,
        "next_pm_date": due,
        "overdue_days": overdue,
        # 예정일이 일주일 안으로 다가오면 임박으로 표시한다
        "pm_soon": bool(due and 0 <= (due - today).days <= 7),
    }


def order_row(o: MaintenanceOrder, today: date | None = None) -> dict:
    today = today or date.today()
    return {
        "order_no": o.order_no,
        "equipment_no": o.equipment_no,
        "equipment_name": o.equipment.name if o.equipment else None,
        "order_type": o.order_type,
        "status": o.status,
        "priority": o.priority,
        "title": o.title,
        "description": o.description,
        "requester": o.requester,
        "request_date": o.request_date,
        "planned_date": o.planned_date,
        "completed_date": o.completed_date,
        "labor_cost": float(o.labor_cost or 0),
        "part_count": len(o.parts),
        # 완료 전인데 예정일이 지났으면 지연
        "is_overdue": bool(o.status in ("REQ", "WIP") and o.planned_date
                           and o.planned_date < today),
        "lead_days": ((o.completed_date - o.request_date).days
                      if o.completed_date else None),
    }


def list_equipment(db: Session, status_filter: str | None = None) -> list[dict]:
    stmt = select(Equipment).order_by(Equipment.equipment_no)
    if status_filter:
        stmt = stmt.where(Equipment.status == status_filter)
    rows = [equipment_row(e) for e in db.scalars(stmt).all()]
    # 지연이 큰 설비를 위로 — 화면에서 바로 눈에 띄게
    rows.sort(key=lambda r: (-r["overdue_days"], r["equipment_no"]))
    return rows


def list_orders(db: Session, status_filter: str | None = None,
                equipment_no: str | None = None, limit: int = 200) -> list[dict]:
    stmt = (select(MaintenanceOrder)
            .options(selectinload(MaintenanceOrder.parts),
                     selectinload(MaintenanceOrder.equipment))
            .order_by(MaintenanceOrder.request_date.desc(),
                      MaintenanceOrder.order_no.desc())
            .limit(limit))
    if status_filter:
        stmt = stmt.where(MaintenanceOrder.status == status_filter)
    if equipment_no:
        stmt = stmt.where(MaintenanceOrder.equipment_no == equipment_no)
    return [order_row(o) for o in db.scalars(stmt).all()]


def order_detail(db: Session, order_no: int) -> dict:
    o = db.get(MaintenanceOrder, order_no)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"정비오더 {order_no} 없음")
    mats = {m.material_no: m for m in db.scalars(select(Material)).all()}
    parts = []
    part_cost = 0.0
    for p in sorted(o.parts, key=lambda x: x.item_no):
        m = mats.get(p.material_no)
        price = float(m.unit_price) if m else 0.0
        part_cost += float(p.quantity) * price
        parts.append({
            "item_no": p.item_no,
            "material_no": p.material_no,
            "description": m.description if m else None,
            "quantity": float(p.quantity),
            "uom": p.uom,
            "unit_price": price,
            "amount": round(float(p.quantity) * price),
            "posted_doc_no": p.posted_doc_no,
        })
    row = order_row(o)
    row["parts"] = parts
    row["part_cost"] = round(part_cost)
    row["total_cost"] = round(part_cost + float(o.labor_cost or 0))
    return row


# ── 생성·완료 ───────────────────────────────────────────────────

def create_order(db: Session, payload: MaintenanceOrderCreate) -> dict:
    eq = db.get(Equipment, payload.equipment_no)
    if not eq:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"설비 {payload.equipment_no} 없음")
    for line in payload.parts:
        if not db.get(Material, line.material_no):
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                f"자재 {line.material_no} 없음")

    o = MaintenanceOrder(
        equipment_no=payload.equipment_no,
        order_type=payload.order_type,
        priority=payload.priority,
        title=payload.title,
        description=payload.description,
        requester=payload.requester,
        request_date=payload.request_date or date.today(),
        planned_date=payload.planned_date,
        status="REQ",
    )
    db.add(o)
    db.flush()
    for idx, line in enumerate(payload.parts, start=1):
        db.add(MaintenanceOrderPart(
            order_no=o.order_no, item_no=idx, material_no=line.material_no,
            quantity=line.quantity, uom=line.uom))

    # 고장(CM) 접수는 설비를 즉시 '고장 정지'로 내려 가동률에 바로 반영한다.
    if payload.order_type == "CM" and eq.status == "RUN":
        eq.status = "DOWN"
    db.commit()
    return order_detail(db, o.order_no)


def complete_order(db: Session, order_no: int,
                   payload: OrderCompleteRequest) -> dict:
    """정비 완료 처리. 부품을 261로 전기해 재고를 빼고 설비를 정상으로 되돌린다."""
    o = db.get(MaintenanceOrder, order_no)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"정비오더 {order_no} 없음")
    if o.status == "DONE":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"정비오더 {order_no}는 이미 완료됨")
    if o.status == "CANCEL":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"취소된 정비오더 {order_no}는 완료할 수 없음")

    ensure_movement_type(db)
    eq = db.get(Equipment, o.equipment_no)
    done_date = payload.completed_date or date.today()

    # 부품이 있으면 자재문서를 전기한다. 재고가 모자라면 여기서 409로 막힌다
    doc_no = None
    unposted = [p for p in o.parts if p.posted_doc_no is None]
    if unposted:
        movement = GoodsMovementCreate(
            posting_date=done_date,
            source="PM",
            lines=[GoodsMovementLine(
                material_no=p.material_no,
                plant_id=eq.plant_id, sloc_id=eq.sloc_id,
                movement_type=MVT_MAINTENANCE_ISSUE,
                quantity=Decimal(str(p.quantity)), uom=p.uom,
            ) for p in unposted],
        )
        result = post_goods_movement(db, movement)   # 내부에서 commit
        doc_no = result.doc_no
        for p in unposted:
            p.posted_doc_no = doc_no

    o.status = "DONE"
    o.completed_date = done_date
    o.labor_cost = Decimal(str(payload.labor_cost))
    if payload.note:
        o.description = f"{o.description or ''}\n[완료] {payload.note}".strip()

    if eq:
        eq.status = "RUN"                       # 정비 끝났으니 다시 가동
        if o.order_type == "PM":
            eq.last_pm_date = done_date         # 이걸 갱신해야 다음 PM 예정일이 밀린다
    db.commit()

    detail = order_detail(db, order_no)
    detail["posted_doc_no"] = doc_no
    return detail


def cancel_order(db: Session, order_no: int) -> dict:
    o = db.get(MaintenanceOrder, order_no)
    if not o:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"정비오더 {order_no} 없음")
    if o.status == "DONE":
        raise HTTPException(status.HTTP_409_CONFLICT, "완료된 오더는 취소할 수 없음")
    o.status = "CANCEL"
    db.commit()
    return order_detail(db, order_no)


# ── KPI ─────────────────────────────────────────────────────────

def maintenance_kpi(db: Session, days: int = 365) -> dict:
    """설비 KPI. 가동률, PM준수율, MTTR, 정비비용.

    재고 KPI와 나란히 보게 될 거라 지표 이름과 단위를 그쪽에 맞췄다.
    """
    today = date.today()
    since = today - timedelta(days=days)
    equipments = db.scalars(select(Equipment)).all()
    total_eq = len(equipments)
    active = [e for e in equipments if e.status != "SCRAP"]
    running = [e for e in active if e.status == "RUN"]
    down = [e for e in active if e.status == "DOWN"]

    # 가동률 = 정상 가동 ÷ (폐기 제외 전체)
    uptime_rate = round(100 * len(running) / len(active), 1) if active else 0.0

    rows = [equipment_row(e, today) for e in active]
    overdue_eq = [r for r in rows if r["overdue_days"] > 0]
    soon_eq = [r for r in rows if r["pm_soon"]]

    orders = db.scalars(
        select(MaintenanceOrder)
        .options(selectinload(MaintenanceOrder.parts))
        .where(MaintenanceOrder.request_date >= since)).all()
    done = [o for o in orders if o.status == "DONE" and o.completed_date]
    open_orders = [o for o in orders if o.status in ("REQ", "WIP")]
    pm_done = [o for o in done if o.order_type == "PM"]
    cm_done = [o for o in done if o.order_type == "CM"]

    # PM 준수율 = 예정일 내 완료 ÷ 예정일이 있는 완료 PM
    pm_planned = [o for o in pm_done if o.planned_date]
    pm_on_time = [o for o in pm_planned if o.completed_date <= o.planned_date]
    pm_compliance = (round(100 * len(pm_on_time) / len(pm_planned), 1)
                     if pm_planned else None)

    # MTTR은 고장(CM) 접수부터 완료까지 걸린 평균 일수. 계획된 PM은 뺀다
    cm_days = [(o.completed_date - o.request_date).days for o in cm_done]
    mttr = round(sum(cm_days) / len(cm_days), 1) if cm_days else None

    # 정비비용 = 인건비 + 소비 부품 금액
    mats = {m.material_no: float(m.unit_price) for m in db.scalars(select(Material)).all()}
    labor = sum(float(o.labor_cost or 0) for o in done)
    parts = sum(float(p.quantity) * mats.get(p.material_no, 0.0)
                for o in done for p in o.parts)

    return {
        "period_days": days,
        "equipment_total": total_eq,
        "equipment_running": len(running),
        "equipment_down": len(down),
        "uptime_rate_pct": uptime_rate,
        "pm_overdue_count": len(overdue_eq),
        "pm_due_soon_count": len(soon_eq),
        "open_order_count": len(open_orders),
        "done_order_count": len(done),
        "pm_ratio_pct": (round(100 * len(pm_done) / len(done), 1) if done else None),
        "pm_compliance_pct": pm_compliance,
        "mttr_days": mttr,
        "labor_cost": round(labor),
        "part_cost": round(parts),
        "total_cost": round(labor + parts),
    }


def pm_schedule(db: Session, horizon_days: int = 30) -> list[dict]:
    """앞으로 N일간의 예방정비 일정과 이미 밀린 건. 지연된 걸 위로 올린다."""
    today = date.today()
    rows = []
    for e in db.scalars(select(Equipment).where(Equipment.status != "SCRAP")).all():
        r = equipment_row(e, today)
        if not r["next_pm_date"]:
            continue
        delta = (r["next_pm_date"] - today).days
        if delta <= horizon_days:
            r["days_left"] = delta
            rows.append(r)
    rows.sort(key=lambda r: r["days_left"])
    return rows
