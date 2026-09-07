"""실 공공데이터 수집 + 실데이터 기반 재시드.

흐름:
  1) 테이블 초기화(clean)
  2) 마스터(조달 품목 30종·창고·이동유형) 적재
  3) 기상청 ASOS 실제 일별 날씨 수집(최근 365일, 지점 108=서울)
  4) 특일정보 실제 공휴일 + 나라장터 입찰공고 + 조달청 MAS 단가 수집
  5) 수집된 실제 날씨·공휴일에 '반응'하는 1년치 거래/스냅샷 생성
  6) 설비 14대 + 1년치 정비 이력 적재
  7) 안전재고·재주문점 산출·반영

init_db.py와 결과는 같은데, 3~4단계 데이터가 합성이 아니라 실제 공공데이터다.

실행(컨테이너):
  docker compose exec -T backend python /workspace/scripts/collect_real_data.py
필요: .env 의 KMA_API_KEY, HOLIDAY_API_KEY (공공데이터포털 발급키)
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "db" / "seeds"))

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
import app.models  # noqa: F401  (mm + maintenance 모델 등록)
from app.services.external import collect_holidays, collect_weather
from app.services.kosis import collect_retail_index
from app.services.nara import collect_bid_notices
from app.services.pps import collect_shop_prices
from seed_maintenance import seed_maintenance
from seed_orm import seed_master, seed_transactions

from app.api.reorder import apply_reorder


def main() -> None:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=364)
    print(f"DB: {settings.database_url.split('@')[-1]}")
    print(f"대상 기간: {start} ~ {end}")

    print("1) 테이블 초기화…")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = SessionLocal()

    def safe(label, fn):
        """외부 수집은 실패해도 롤백 후 계속 — 핵심 데이터(품목·거래)를 지킨다."""
        try:
            r = fn()
            print(f"   {label} → {r}")
            return r if isinstance(r, dict) else {}
        except Exception as e:  # noqa: BLE001
            db.rollback()
            print(f"   ⚠️ {label} 실패(건너뜀): {type(e).__name__}: {e}")
            return {}

    try:
        print("2) 마스터(상품·창고·이동유형) 적재…")
        seed_master(db)

        print("3) 기상청 실제 날씨 수집…")
        w = safe("날씨", lambda: collect_weather(db, start, end))

        print("4) 특일정보 실제 공휴일 수집…")
        for yr in range(start.year, end.year + 1):
            safe(f"공휴일 {yr}", lambda y=yr: collect_holidays(db, y))

        print("4b) 조달청 나라장터 입찰공고(물품) 실수요 수집…")
        # 조달청 API는 조회기간을 약 1개월로 제한 → 최근 30일
        safe("입찰공고", lambda: collect_bid_notices(db, end - timedelta(days=30), end, rows=300))

        print("4c) 조달청 종합쇼핑몰 MAS 실 계약단가 수집…")
        safe("종합쇼핑몰 단가", lambda: collect_shop_prices(db, days=7, rows=100))

        print("4d) 통계청 KOSIS 의류 소매판매액지수 수집(선택)…")
        safe("KOSIS", lambda: collect_retail_index(db))

        real_ok = w.get("collected", 0) > 0
        if not real_ok:
            print("⚠️  실제 날씨가 0건입니다(키 미설정/미활성). 거래는 합성 날씨로 보정됩니다.")

        print("5) 실데이터 기반 거래·스냅샷 생성…")
        info = seed_transactions(db, days=365, use_real_weather=real_ok)
        print(f"   → {info}")

        # 설비 정비는 부품 소비가 자재·재고를 참조해서 거래 적재 뒤에 와야 한다
        print("6) 설비·정비 이력 적재…")
        print(f"   → {seed_maintenance(db)}")

        # 거래 이력이 있어야 일수요 통계가 나오니 마지막에 반영한다
        print("7) 안전재고·재주문점 산출·반영…")
        r = apply_reorder(lead_time_days=3, review_days=7, service_level=0.95, db=db)
        print(f"   → {r['message']}")

        print("✅ 실 공공데이터 적재 완료")
    finally:
        db.close()


if __name__ == "__main__":
    main()
