"""StockCast 분석(안전재고·재주문점) → Odoo 재주문 규칙으로 write-back.

StockCast가 실 공공데이터 기반으로 계산한 재주문점/발주상한을 Odoo의
stock.warehouse.orderpoint(재주문 규칙)에 반영한다. 이후 Odoo가 재고가
재주문점 이하로 떨어지면 자동으로 보충을 제안한다.

실행: docker compose exec -T backend python /workspace/scripts/odoo_sync_reorder.py
"""
from __future__ import annotations

import os
import sys
import xmlrpc.client

from app.core.database import SessionLocal
from app.api.reorder import _analyze

URL = os.getenv("ODOO_URL", "http://host.docker.internal:8069")
DB = os.getenv("ODOO_DB", "stockcast")
USER = os.getenv("ODOO_USERNAME", "admin@stockcast.local")
SECRET = os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY", "")


def main() -> int:
    if not SECRET:
        print("❌ ODOO_PASSWORD(또는 ODOO_API_KEY) 미설정 — .env 확인.")
        return 1

    # 1) StockCast 분석: 실데이터 기반 안전재고·재주문점·발주상한
    db = SessionLocal()
    try:
        recs = _analyze(db, lead_time=3, review=7, service_level=0.95,
                        only_need=False)
    finally:
        db.close()
    print(f"StockCast 분석 완료 — {len(recs)}개 품목")

    # 2) Odoo 접속
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    uid = common.authenticate(DB, USER, SECRET, {})
    if not uid:
        print("❌ Odoo 인증 실패 — .env 확인.")
        return 1
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

    def call(model, method, *args, **kw):
        return models.execute_kw(DB, uid, SECRET, model, method, list(args), kw)

    # 3) 창고/위치
    wh = call("stock.warehouse", "search", [])
    if not wh:
        print("❌ 창고를 찾지 못함.")
        return 1
    wh_id = wh[0]
    loc_id = call("stock.warehouse", "read", wh_id,
                  fields=["lot_stock_id"])[0]["lot_stock_id"][0]

    # 4) 품목별 재주문 규칙 생성/갱신
    created, updated, skipped = 0, 0, 0
    for r in recs:
        prod = call("product.product", "search",
                    [["default_code", "=", r["material_no"]]])
        if not prod:
            skipped += 1
            continue
        pid = prod[0]
        vals = {
            "product_id": pid,
            "warehouse_id": wh_id,
            "location_id": loc_id,
            "product_min_qty": round(float(r["reorder_point"]), 2),
            "product_max_qty": round(float(r["order_up_to"]), 2),
        }
        op = call("stock.warehouse.orderpoint", "search",
                  [["product_id", "=", pid]])
        if op:
            call("stock.warehouse.orderpoint", "write", op, vals); updated += 1
        else:
            call("stock.warehouse.orderpoint", "create", vals); created += 1

    print(f"✅ Odoo 재주문 규칙 반영 — 신규 {created} · 갱신 {updated} · 건너뜀 {skipped}")
    print("Odoo 재고관리 → 운영 → 재주문 규칙 에서 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
