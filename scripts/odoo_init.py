"""Odoo DB 생성 + 재고관리 앱 설치 — 브라우저 마법사 대신 XML-RPC 로.

서버를 새로 만들면 Odoo 볼륨이 비어 있어서 DB 생성 마법사를 화면에서 돌려야 했다.
같은 일을 스크립트로 한다. 이미 있으면 건너뛰므로 여러 번 돌려도 된다.

.env:
  ODOO_URL, ODOO_DB, ODOO_USERNAME
  ODOO_PASSWORD         새 DB 의 관리자 비밀번호로 쓴다
  ODOO_MASTER_PASSWORD  (선택) 없으면 infra/odoo/odoo.conf 의 admin_passwd

실행:
  docker compose $COMPOSE_FILES exec -T backend python /workspace/scripts/odoo_init.py
"""
from __future__ import annotations

import os
import sys
import xmlrpc.client
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = os.getenv("ODOO_URL", "http://host.docker.internal:8069")
DB = os.getenv("ODOO_DB", "stockcast")
USER = os.getenv("ODOO_USERNAME", "admin@stockcast.local")
SECRET = os.getenv("ODOO_PASSWORD", "")


def master_password() -> str:
    if os.getenv("ODOO_MASTER_PASSWORD"):
        return os.environ["ODOO_MASTER_PASSWORD"]
    conf = ROOT / "infra" / "odoo" / "odoo.conf"
    for line in conf.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("admin_passwd"):
            return line.split("=", 1)[1].strip()
    return ""


def main() -> int:
    if not SECRET:
        print("❌ ODOO_PASSWORD 미설정 — 새 DB 의 관리자 비밀번호로 쓴다. .env 확인.")
        return 1

    dbs = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/db")
    if DB in dbs.list():
        print(f"DB '{DB}' 이미 있음 — 생성 건너뜀")
    else:
        # 한국어, 데모 데이터 없이 만든다. 한국어 팩 설치 때문에 몇 분 걸린다.
        dbs.create_database(master_password(), DB, False, "ko_KR", SECRET, USER, "KR")
        print(f"✅ DB '{DB}' 생성")

    uid = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/common").authenticate(DB, USER, SECRET, {})
    if not uid:
        print("❌ 인증 실패 — 기존 DB 가 다른 비밀번호로 만들어져 있다")
        return 1
    models = xmlrpc.client.ServerProxy(f"{URL}/xmlrpc/2/object")

    def call(model, method, *args, **kw):
        return models.execute_kw(DB, uid, SECRET, model, method, list(args), kw)

    ids = call("ir.module.module", "search", [["name", "=", "stock"]])
    if call("ir.module.module", "read", ids, fields=["state"])[0]["state"] == "installed":
        print("재고관리 앱 이미 설치됨")
    else:
        call("ir.module.module", "button_immediate_install", ids)
        print("✅ 재고관리 앱 설치")
    print("다음: odoo_load.py → odoo_sync_reorder.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
