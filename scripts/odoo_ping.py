"""Odoo 연결 확인 — XML-RPC로 인증/버전/모델 접근을 점검한다.

사용:
    pip install python-dotenv
    python scripts/odoo_ping.py
환경변수(.env): ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY
"""
from __future__ import annotations

import os
import sys
import xmlrpc.client

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

URL = os.getenv("ODOO_URL", "http://localhost:8069")
DB = os.getenv("ODOO_DB", "stockcast")
USER = os.getenv("ODOO_USERNAME", "admin@stockcast.local")
KEY = os.getenv("ODOO_API_KEY", "")


def main() -> int:
    if not KEY:
        print("❌ ODOO_API_KEY가 비어 있습니다. .env에 키를 넣으세요.")
        return 1
    common = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common")
    ver = common.version()
    print(f"✅ Odoo 접속: {URL}  버전 {ver.get('server_version')}")

    uid = common.authenticate(DB, USER, KEY, {})
    if not uid:
        print("❌ 인증 실패 — DB명/계정/API키를 확인하세요.")
        return 1
    print(f"✅ 인증 성공 — uid={uid}")

    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")
    n_prod = models.execute_kw(DB, uid, KEY, "product.template", "search_count", [[]])
    n_quant = models.execute_kw(DB, uid, KEY, "stock.quant", "search_count", [[]])
    print(f"✅ 모델 접근 OK — product.template {n_prod}건, stock.quant {n_quant}건")
    print("\n연결 정상입니다. 다음 단계(상품·재고 적재)로 진행 가능합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
