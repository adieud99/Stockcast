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
import app.models  # noqa: F401  (mm + maintenance 모델 등록)
from app.models.maintenance import Equipment
from app.models.mm import Material
from seed_maintenance import seed_maintenance
from seed_orm import seed_all

from app.api.reorder import apply_reorder


def main() -> None:
    print(f"DB 연결: {settings.database_url.split('@')[-1]}")
    print("1) 테이블 생성 중...")
    Base.metadata.create_all(engine)
    print(f"   완료 — 테이블 {len(Base.metadata.tables)}개")

    db = SessionLocal()
    try:
        count = db.scalar(select(func.count()).select_from(Material))
        if count and count > 0:
            print(f"2) 이미 자재 데이터 {count}건 존재 — 거래 시드 건너뜀")
        else:
            print("2) 시드 적재 중 (조달 품목 30종 + 1년치 거래)...")
            info = seed_all(db, days=365)
            print(f"   완료 — {info}")

        # 설비 유지보수는 자재 시드 뒤에 넣는다.
        # 정비 부품 소비가 자재·재고를 참조해서 순서가 중요하다.
        if db.scalar(select(func.count()).select_from(Equipment)):
            print("3) 설비 데이터 이미 존재 — 유지보수 시드 건너뜀")
        else:
            print("3) 설비·정비 이력 적재 중...")
            print(f"   완료 — {seed_maintenance(db)}")

        # 안전재고·재주문점은 거래 이력이 있어야 계산돼서 마지막에 반영한다.
        # 이걸 빼먹으면 safety_stock과 reorder_point가 0으로 남아서
        # KPI의 '발주 필요' 카드가 늘 0으로 보인다.
        print("4) 안전재고·재주문점 산출·반영 중...")
        result = apply_reorder(lead_time_days=3, review_days=7,
                               service_level=0.95, db=db)
        print(f"   완료 — {result['message']}")
    finally:
        db.close()
    print("✅ DB 초기화 완료")


if __name__ == "__main__":
    main()
