"""StockCast 조달 품목·재고를 Odoo(실제 ERP)에 적재 — XML-RPC.

백엔드 컨테이너에서 실행하며, 호스트의 Odoo(localhost:8069)에는
host.docker.internal 로 접속한다.

.env 필요:
  ODOO_URL=http://host.docker.internal:8069
  ODOO_DB=stockcast
  ODOO_USERNAME=admin@stockcast.local
  ODOO_PASSWORD=stockcast        # 또는 ODOO_API_KEY

실행:
  docker compose exec -T backend python /workspace/scripts/odoo_load.py
"""
from __future__ import annotations

import os
import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db" / "seeds"))
from seed_orm import GROUPS, MATERIALS  # noqa: E402

URL = os.getenv("ODOO_URL", "http://host.docker.internal:8069")
DB = os.getenv("ODOO_DB", "stockcast")
USER = os.getenv("ODOO_USERNAME", "admin@stockcast.local")
SECRET = os.getenv("ODOO_PASSWORD") or os.getenv("ODOO_API_KEY", "")


def main() -> int:
    if not SECRET:
        print("❌ ODOO_PASSWORD(또는 ODOO_API_KEY) 미설정 — .env 확인.")
        return 1

    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    print(f"Odoo 접속: {URL}  버전 {common.version().get('server_version')}")
    uid = common.authenticate(DB, USER, SECRET, {})
    if not uid:
        print("❌ 인증 실패 — DB/계정/비밀번호 확인.")
        return 1
    print(f"✅ 인증 성공 uid={uid}")
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

    def call(model, method, *args, **kw):
        return models.execute_kw(DB, uid, SECRET, model, method, list(args), kw)

    # 1) 품목 카테고리(우리 그룹) 생성/조회
    cat_id: dict[str, int] = {}
    for code, name in GROUPS:
        found = call("product.category", "search", [["name", "=", name]])
        cat_id[code] = found[0] if found else call(
            "product.category", "create", {"name": name})
    print(f"카테고리 {len(cat_id)}개 준비")

    # 2) 내부 재고 위치(Stock) 찾기
    loc = call("stock.location", "search", [["usage", "=", "internal"]])
    if not loc:
        print("❌ 내부 재고위치를 찾지 못함 — 재고관리(Inventory) 앱 설치 확인.")
        return 1
    stock_loc = loc[0]

    # 3) 품목 생성(있으면 갱신) + 초기 재고
    created, updated = 0, 0
    for mno, name, grp, sloc, base, tc, pc, price in MATERIALS:
        cost = round(price * 0.7)
        vals = {
            "name": name,
            "default_code": mno,            # 품목코드 = 우리 자재번호
            "list_price": price,            # 판매단가
            "standard_price": cost,         # 원가
            "categ_id": cat_id[grp],
            "type": "consu",                # Odoo 18: 저장가능 품목
            "is_storable": True,
        }
        exist = call("product.template", "search", [["default_code", "=", mno]])
        if exist:
            call("product.template", "write", exist, vals); updated += 1
            tmpl_id = exist[0]
        else:
            tmpl_id = call("product.template", "create", vals); created += 1

        # 변형(variant) id 조회 후 초기 재고 = 일평균수요×120
        variant = call("product.template", "read", tmpl_id,
                       fields=["product_variant_id"])
        pv_id = variant[0]["product_variant_id"][0]
        qty = base * 120
        # 재고는 stock.quant 수량을 직접 설정(멱등) — None 반환 메서드 회피
        exist_q = call("stock.quant", "search",
                       [["product_id", "=", pv_id], ["location_id", "=", stock_loc]])
        if exist_q:
            call("stock.quant", "write", exist_q, {"quantity": qty})
        else:
            call("stock.quant", "create", {
                "product_id": pv_id, "location_id": stock_loc, "quantity": qty})

    n_prod = call("product.template", "search_count", [])
    print(f"✅ 완료 — 신규 {created} · 갱신 {updated} · 전체 품목 {n_prod}")
    print("Odoo 재고관리 → 품목 에서 30종과 재고를 확인하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
