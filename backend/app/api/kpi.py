"""백오피스 KPI 집계 API — 대시보드(W8)가 호출."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.mm import (
    Material, MaterialDocHeader, MaterialDocItem, MaterialGroup, MovementType,
    Stock, StockSnapshotHistory,
)

router = APIRouter(prefix="/api/kpi", tags=["KPI 대시보드"])


def _issued_by_material(db: Session, since: date) -> dict[str, float]:
    """기간 내 자재별 출고량(이동유형 방향 -1) 합계."""
    stmt = (
        select(MaterialDocItem.material_no,
               func.sum(MaterialDocItem.quantity))
        .join(MaterialDocHeader, MaterialDocHeader.doc_no == MaterialDocItem.doc_no)
        .join(MovementType, MovementType.code == MaterialDocItem.movement_type)
        .where(MovementType.direction == -1,
               MaterialDocHeader.posting_date >= since)
        .group_by(MaterialDocItem.material_no)
    )
    return {m: float(q or 0) for m, q in db.execute(stmt).all()}


def _avg_inventory(db: Session) -> dict[str, float]:
    """자재별 평균 재고(스냅샷 이력 기준)."""
    stmt = (select(StockSnapshotHistory.material_no,
                   func.avg(StockSnapshotHistory.unrestricted_qty))
            .group_by(StockSnapshotHistory.material_no))
    return {m: float(a or 0) for m, a in db.execute(stmt).all()}


@router.get("/summary", summary="핵심 KPI 요약")
def kpi_summary(db: Session = Depends(get_db)):
    today = date.today()
    since = today - timedelta(days=365)

    sku_count = db.scalar(select(func.count()).select_from(Material))
    total_stock = db.scalar(select(func.coalesce(func.sum(Stock.unrestricted_qty), 0)))

    # 재고자산금액(운전자본) = Σ(재고수량 × 판매단가)
    inventory_value = db.scalar(
        select(func.coalesce(func.sum(Stock.unrestricted_qty * Material.unit_price), 0))
        .select_from(Stock).join(Material, Material.material_no == Stock.material_no)
    )

    # 발주 필요(재주문점 이하) 품목 수 — apply 이후 reorder_point가 채워진 경우
    reorder_needed = db.scalar(
        select(func.count()).select_from(Stock)
        .where(Stock.reorder_point > 0,
               Stock.unrestricted_qty <= Stock.reorder_point)
    )
    # 안전재고 이하 품목 수(결품 위험)
    below_safety = db.scalar(
        select(func.count()).select_from(Stock)
        .where(Stock.safety_stock > 0,
               Stock.unrestricted_qty <= Stock.safety_stock)
    )

    # 재고회전율(전체) = 총출고 / 평균재고
    issued = _issued_by_material(db, since)
    avg_inv = _avg_inventory(db)
    turns = []
    for m, iss in issued.items():
        ai = avg_inv.get(m, 0)
        if ai > 0:
            turns.append(iss / ai)
    avg_turnover = round(sum(turns) / len(turns), 2) if turns else 0.0

    # 결품률 = 스냅샷 중 재고 0 비율
    total_snap = db.scalar(select(func.count()).select_from(StockSnapshotHistory)) or 0
    zero_snap = db.scalar(
        select(func.count()).select_from(StockSnapshotHistory)
        .where(StockSnapshotHistory.unrestricted_qty <= 0)) or 0
    stockout_rate = round(100 * zero_snap / total_snap, 2) if total_snap else 0.0

    return {
        "sku_count": sku_count,
        "total_stock_qty": float(total_stock),
        "inventory_value": float(inventory_value),
        "reorder_needed_count": reorder_needed,
        "below_safety_count": below_safety,
        "avg_turnover": avg_turnover,
        "stockout_rate_pct": stockout_rate,
    }


@router.get("/turnover", summary="자재별 재고회전율")
def kpi_turnover(db: Session = Depends(get_db)):
    since = date.today() - timedelta(days=365)
    issued = _issued_by_material(db, since)
    avg_inv = _avg_inventory(db)
    mats = {m.material_no: m for m in db.scalars(select(Material)).all()}
    out = []
    for m, iss in issued.items():
        ai = avg_inv.get(m, 0)
        out.append({
            "material_no": m,
            "description": mats[m].description if m in mats else None,
            "issued": round(iss, 1),
            "avg_inventory": round(ai, 1),
            "turnover": round(iss / ai, 2) if ai > 0 else None,
        })
    out.sort(key=lambda r: (r["turnover"] is None, -(r["turnover"] or 0)))
    return out


@router.get("/stock-by-group", summary="자재그룹별 재고 분포")
def kpi_stock_by_group(db: Session = Depends(get_db)):
    stmt = (
        select(MaterialGroup.name, func.coalesce(func.sum(Stock.unrestricted_qty), 0))
        .select_from(Stock)
        .join(Material, Material.material_no == Stock.material_no)
        .join(MaterialGroup, MaterialGroup.group_code == Material.group_code)
        .group_by(MaterialGroup.name)
    )
    return [{"group": g, "qty": float(q)} for g, q in db.execute(stmt).all()]


@router.get("/monthly-issues", summary="월별 출고 추이")
def kpi_monthly_issues(
    months: int = Query(12, ge=1, le=24),
    db: Session = Depends(get_db),
):
    since = date.today() - timedelta(days=months * 31)
    rows = db.execute(
        select(MaterialDocHeader.posting_date, MaterialDocItem.quantity)
        .join(MaterialDocItem, MaterialDocItem.doc_no == MaterialDocHeader.doc_no)
        .join(MovementType, MovementType.code == MaterialDocItem.movement_type)
        .where(MovementType.direction == -1,
               MaterialDocHeader.posting_date >= since)
    ).all()
    agg: dict[str, float] = {}
    for d, q in rows:
        ym = f"{d.year}-{d.month:02d}"
        agg[ym] = agg.get(ym, 0) + float(q)
    return [{"month": k, "issued": round(v, 1)} for k, v in sorted(agg.items())]


@router.get("/abc", summary="ABC 분석 (매출액 파레토)")
def kpi_abc(db: Session = Depends(get_db)):
    """최근 1년 출고금액(매출액) 기준 파레토 → A(누적70%)·B(90%)·C 등급."""
    since = date.today() - timedelta(days=365)
    issued = _issued_by_material(db, since)
    mats = {m.material_no: m for m in db.scalars(select(Material)).all()}
    rows = []
    for mno, qty in issued.items():
        price = float(mats[mno].unit_price) if mno in mats else 0.0
        rows.append({
            "material_no": mno,
            "description": mats[mno].description if mno in mats else None,
            "sales_value": round(qty * price),
        })
    rows.sort(key=lambda r: -r["sales_value"])
    total = sum(r["sales_value"] for r in rows) or 1
    cum = 0
    for r in rows:
        cum += r["sales_value"]
        ratio = 100 * cum / total
        r["cum_ratio_pct"] = round(ratio, 1)
        r["grade"] = "A" if ratio <= 70 else ("B" if ratio <= 90 else "C")
    return rows
