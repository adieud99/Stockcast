"""Odoo(실제 ERP) 읽기 연동 — XML-RPC.

StockCast 대시보드가 Odoo의 실시간 재고/재주문 규칙을 조회할 때 사용한다.
연결 정보는 settings(.env)의 ODOO_* 값을 따른다.
"""
from __future__ import annotations

import xmlrpc.client

from app.core.config import settings


def _connect():
    url = settings.odoo_url
    secret = settings.odoo_password or settings.odoo_api_key
    if not secret:
        raise RuntimeError("ODOO_PASSWORD/ODOO_API_KEY 미설정")
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
    uid = common.authenticate(settings.odoo_db, settings.odoo_username, secret, {})
    if not uid:
        raise RuntimeError("Odoo 인증 실패 — DB/계정/비밀번호 확인")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)
    return uid, secret, models


def fetch_stock() -> list[dict]:
    """Odoo 품목별 실시간 재고(on-hand)·판매단가."""
    uid, secret, models = _connect()

    def call(model, method, *args, **kw):
        return models.execute_kw(settings.odoo_db, uid, secret,
                                 model, method, list(args), kw)

    ids = call("product.product", "search", [["default_code", "!=", False]])
    rows = call("product.product", "read", ids,
                fields=["default_code", "name", "qty_available",
                        "list_price", "categ_id"])
    out = []
    for r in rows:
        out.append({
            "material_no": r.get("default_code"),
            "name": r.get("name"),
            "qty_on_hand": r.get("qty_available"),
            "list_price": r.get("list_price"),
            "category": r["categ_id"][1] if r.get("categ_id") else None,
        })
    out.sort(key=lambda x: x["material_no"] or "")
    return out


def apply_nfc_movement(material_no: str, movement_type: str, qty: float) -> dict:
    """NFC 스캔(입고 101/561 = +, 출고 201 = −)을 Odoo 실재고에 반영."""
    uid, secret, models = _connect()

    def call(model, method, *args, **kw):
        return models.execute_kw(settings.odoo_db, uid, secret,
                                 model, method, list(args), kw)

    prod = call("product.product", "search", [["default_code", "=", material_no]])
    if not prod:
        raise RuntimeError(f"Odoo에 품목 {material_no}이(가) 없습니다")
    pv = prod[0]
    loc = call("stock.location", "search", [["usage", "=", "internal"]])
    if not loc:
        raise RuntimeError("Odoo 내부 재고위치를 찾지 못했습니다")
    stock_loc = loc[0]

    quants = call("stock.quant", "search",
                  [["product_id", "=", pv], ["location_id", "=", stock_loc]])
    cur = 0.0
    if quants:
        cur = call("stock.quant", "read", quants[0],
                   fields=["quantity"])[0]["quantity"] or 0.0

    direction = 1 if movement_type in ("101", "561") else -1
    new_qty = cur + direction * qty
    if new_qty < 0:
        raise RuntimeError(f"재고 부족 — 현재 {cur}개로 출고 불가")

    if quants:
        call("stock.quant", "write", quants[0], {"quantity": new_qty})
    else:
        call("stock.quant", "create",
             {"product_id": pv, "location_id": stock_loc, "quantity": new_qty})

    name = call("product.product", "read", pv, fields=["name"])[0]["name"]
    return {"material_no": material_no, "name": name, "direction": direction,
            "qty": qty, "prev_qty": cur, "new_qty": new_qty}
