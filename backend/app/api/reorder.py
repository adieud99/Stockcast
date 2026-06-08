"""재고·발주 권고 API — 안전재고·ROP 계산 및 결품 위험 품목 도출."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.mm import Material, Stock

ANALYTICS = Path(__file__).resolve().parents[3] / "analytics"
if str(ANALYTICS) not in sys.path:
    sys.path.insert(0, str(ANALYTICS))

from forecast.data_prep import build_features  # noqa: E402
from inventory.reorder import demand_stats, recommend  # noqa: E402

router = APIRouter(prefix="/api/reorder", tags=["재고·발주"])


def _analyze(db: Session, lead_time: int, review: int, service_level: float,
            only_need: bool) -> list[dict]:
    df = build_features(db)
    stocks = {(s.material_no, s.plant_id, s.sloc_id): s
              for s in db.scalars(select(Stock)).all()}
    mats = {m.material_no: m for m in db.scalars(select(Material)).all()}

    result = []
    for (mno, pl, sl), st in stocks.items():
        g = df[df.material_no == mno]
        stats = demand_stats(g) if not g.empty else {"avg_daily_demand": 0, "daily_std": 0}
        rec = recommend(float(st.unrestricted_qty), stats["avg_daily_demand"],
                        stats["daily_std"], lead_time, review, service_level)
        rec["material_no"] = mno
        rec["description"] = mats[mno].description if mno in mats else None
        rec["plant_id"], rec["sloc_id"] = pl, sl
        if (not only_need) or rec["need_order"]:
            result.append(rec)
    # 결품 위험(공급일수 적은) 순 정렬
    result.sort(key=lambda r: (r["days_of_supply"] is None, r["days_of_supply"] or 0))
    return result


@router.get("", summary="발주 권고 목록 (안전재고·ROP·권장 발주량)")
def reorder_list(
    lead_time_days: int = Query(3, ge=1, description="리드타임(일)"),
    review_days: int = Query(7, ge=1, description="발주주기(일)"),
    service_level: float = Query(0.95, description="목표 서비스수준(0.90/0.95/0.99)"),
    only_need: bool = Query(False, description="발주 필요 품목만"),
    db: Session = Depends(get_db),
):
    return _analyze(db, lead_time_days, review_days, service_level, only_need)


@router.post("/apply", summary="계산된 안전재고·ROP를 재고에 반영")
def apply_reorder(
    lead_time_days: int = Query(3, ge=1),
    review_days: int = Query(7, ge=1),
    service_level: float = Query(0.95),
    db: Session = Depends(get_db),
):
    """산출된 안전재고·재주문점을 stock 테이블에 저장한다."""
    recs = _analyze(db, lead_time_days, review_days, service_level, only_need=False)
    updated = 0
    for r in recs:
        st = db.get(Stock, (r["material_no"], r["plant_id"], r["sloc_id"]))
        if st:
            st.safety_stock = Decimal(str(r["safety_stock"]))
            st.reorder_point = Decimal(str(r["reorder_point"]))
            updated += 1
    db.commit()
    return {"updated": updated, "message": f"{updated}개 품목의 안전재고·재주문점 갱신 완료"}
