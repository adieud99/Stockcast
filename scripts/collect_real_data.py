"""실 공공데이터 수집 + 실데이터 기반 재시드.

흐름:
  1) 테이블 초기화(clean)
  2) 마스터(29종 의류·창고·이동유형) 적재
  3) 기상청 ASOS 실제 일별 날씨 수집(최근 365일, 지점 108=서울)
  4) 특일정보 실제 공휴일 수집(범위 내 연도)
  5) 수집된 실제 날씨·공휴일에 '반응'하는 1년치 거래/스냅샷 생성

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
import app.models.mm  # noqa: F401
from app.services.external import collect_holidays, collect_weather
from app.services.kosis import collect_retail_index
from app.services.nara import collect_bid_notices
from app.services.pps import collect_shop_prices
from seed_orm import seed_master, seed_transactions


def main() -> None:
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=364)
    print(f"DB: {settings.database_url.split('@')[-1]}")
    print(f"대상 기간: {start} ~ {end}")

    print("1) 테이블 초기화…")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        print("2) 마스터(상품·창고·이동유형) 적재…")
        seed_master(db)

        print("3) 기상청 실제 날씨 수집…")
        w = collect_weather(db, start, end)
        print(f"   → {w}")

        print("4) 특일정보 실제 공휴일 수집…")
        for yr in range(start.year, end.year + 1):
            h = collect_holidays(db, yr)
            print(f"   {yr}: {h}")

        print("4b) 조달청 나라장터 입찰공고(물품) 실수요 수집…")
        b = collect_bid_notices(db, end - timedelta(days=90), end, rows=300)
        print(f"   → {b}")

        print("4c) 조달청 종합쇼핑몰 MAS 실 계약단가 수집…")
        sp = collect_shop_prices(db, days=7, rows=100)
        print(f"   → {sp}")

        print("4d) 통계청 KOSIS 의류 소매판매액지수 수집(선택)…")
        rt = collect_retail_index(db)
        print(f"   → {rt}")

        real_ok = w.get("collected", 0) > 0
        if not real_ok:
            print("⚠️  실제 날씨가 0건입니다(키 미설정/미활성). 거래는 합성 날씨로 보정됩니다.")

        print("5) 실데이터 기반 거래·스냅샷 생성…")
        info = seed_transactions(db, days=365, use_real_weather=real_ok)
        print(f"   → {info}")
        print("✅ 실 공공데이터 적재 완료")
    finally:
        db.close()


if __name__ == "__main__":
    main()
