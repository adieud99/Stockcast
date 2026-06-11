"""Odoo(실제 ERP) 연동 조회 API — 대시보드 역방향 연동."""
from __future__ import annotations

from fastapi import APIRouter

from app.services.odoo import fetch_stock

router = APIRouter(prefix="/api/odoo", tags=["Odoo 연동"])


@router.get("/stock", summary="Odoo 실시간 재고")
def odoo_stock():
    """Odoo가 보유한 실물 재고(on-hand)를 조회. 연결 실패 시 graceful 응답."""
    try:
        items = fetch_stock()
        total_value = sum((i["qty_on_hand"] or 0) * (i["list_price"] or 0)
                          for i in items)
        return {"connected": True, "count": len(items),
                "inventory_value": round(total_value), "items": items}
    except Exception as e:  # noqa: BLE001
        return {"connected": False, "error": str(e), "count": 0,
                "inventory_value": 0, "items": []}
