"""Odoo(실제 ERP) 연동 조회 API — 대시보드 역방향 연동."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.mm import NfcTag
from app.services.odoo import apply_nfc_movement, fetch_stock

router = APIRouter(prefix="/api/odoo", tags=["Odoo 연동"])


@router.get("/info", summary="Odoo 접속 정보(대시보드 바로가기용)")
def odoo_info(request: Request):
    """대시보드에서 Odoo로 바로 들어가도록 웹 주소 제공.
    대시보드와 같은 호스트의 8069 포트(localhost 또는 서버 공인IP)를 가리킨다."""
    host = request.url.hostname or "localhost"
    return {"web_url": f"http://{host}:8069", "db": settings.odoo_db}


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


class OdooScan(BaseModel):
    tag_uid: str
    movement_type: str = "101"
    quantity: float = 1


@router.post("/nfc-scan", summary="NFC 스캔을 Odoo 실재고에 반영")
def odoo_nfc_scan(body: OdooScan, db: Session = Depends(get_db)):
    """NFC 태그 스캔 → 태그 매핑 품목을 찾아 Odoo 실재고를 입고/출고 처리."""
    tag = db.get(NfcTag, body.tag_uid)
    if not tag:
        return {"ok": False, "error": f"미등록 태그: {body.tag_uid}"}
    try:
        return {"ok": True, **apply_nfc_movement(
            tag.material_no, body.movement_type, body.quantity)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
