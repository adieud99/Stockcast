"""DB 초기화 — 테이블 생성 + 시드 적재.

설정된 DATABASE_URL(Oracle/PostgreSQL/SQLite) 어디든 동작.
Oracle ADB에 올리려면: backend/.env 에 아래를 넣고 실행
  DATABASE_URL=oracle+oracledb://DA2607:Data2607@dinkdb_medium
  ORACLE_WALLET_DIR=/Users/adieu/java-intellij/sec02/Wallet_DinkDB
  ORACLE_WALLET_PASSWORD=<wallet 다운로드 시 설정한 비번>

실행:  python init_db.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db" / "seeds"))

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
import app.models.mm  # noqa: F401  (모델 등록)
from app.models.mm import Material
from seed_orm import seed_all


def main() -> None:
    print(f"DB 연결: {settings.database_url.split('@')[-1]}")
    print("1) 테이블 생성 중...")
    Base.metadata.create_all(engine)
    print(f"   완료 — 테이블 {len(Base.metadata.tables)}개")

    db = SessionLocal()
    try:
        count = db.scalar(select(func.count()).select_from(Material))
        if count and count > 0:
            print(f"2) 이미 데이터 {count}건 존재 — 시드 건너뜀")
            return
        print("2) 시드 적재 중 (상품 11종 + 1년치 거래)...")
        info = seed_all(db, days=365)
        print(f"   완료 — {info}")
    finally:
        db.close()
    print("✅ DB 초기화 완료")


if __name__ == "__main__":
    main()
