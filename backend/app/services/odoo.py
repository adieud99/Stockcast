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
