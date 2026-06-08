"""
StockCast — 시계열 거래/날씨 시드 생성기

목적:
  수요예측(5단계) 다중회귀가 학습할 수 있도록, '기온과 상관관계가 있는'
  현실적인 출고 이력과 날씨 데이터를 생성한다.

설계 의도(왜 이렇게?):
  - 난방용품(HEAT): 기온이 낮을수록 출고↑ (음의 상관)
  - 냉방용품(COOL): 기온이 높을수록 출고↑ (양의 상관)
  - 생활/음료: 계절 영향 적음 + 주말/공휴일 가중
  → 회귀분석에서 "기온 -1℃ → 난방 출고 +x%" 같은 해석이 나오도록 의도적으로 신호를 심는다.

실행:
  python db/seeds/seed_transactions.py
환경변수 DATABASE_URL_PSYCOPG (psycopg 연결 문자열) 사용. 없으면 로컬 기본값.
"""
from __future__ import annotations

import math
import os
import random
from datetime import date, timedelta

import psycopg

random.seed(42)  # 재현 가능

DSN = os.environ.get(
    "DATABASE_URL_PSYCOPG",
    "host=localhost port=5432 dbname=erp_nfc user=erp password=erp_pass",
)

# 시뮬레이션 기간: 과거 365일 ~ 어제
END_DATE = date.today() - timedelta(days=1)
START_DATE = END_DATE - timedelta(days=364)

# 한국 주요 공휴일(고정일 위주, 데모 단순화)
HOLIDAYS = {
    (1, 1): "신정", (3, 1): "삼일절", (5, 5): "어린이날",
    (6, 6): "현충일", (8, 15): "광복절", (10, 3): "개천절",
    (10, 9): "한글날", (12, 25): "성탄절",
}

# 자재별 수요 모델 파라미터
#   base: 일 평균 기본 출고량, temp_coef: 기온 1℃당 출고 변화량(±)
MATERIALS = {
    "100001": {"base": 12, "temp_coef": -0.9, "sloc": "0002"},  # 전기 히터
    "100002": {"base": 10, "temp_coef": -0.7, "sloc": "0002"},  # 온수 매트
    "100003": {"base": 25, "temp_coef": -1.4, "sloc": "0002"},  # 핫팩
    "200001": {"base": 11, "temp_coef":  0.8, "sloc": "0002"},  # 선풍기
    "200002": {"base": 18, "temp_coef":  1.1, "sloc": "0002"},  # 미니선풍기
    "300001": {"base": 40, "temp_coef":  0.3, "sloc": "0001"},  # 생수 (더울수록 약간↑)
    "300002": {"base": 30, "temp_coef":  0.0, "sloc": "0001"},  # 물티슈 (계절 무관)
}
PLANT = "1000"


def seasonal_temp(d: date) -> float:
    """서울 기온 근사: 연중 사인 곡선(최저 1월, 최고 8월) + 잡음."""
    day_of_year = d.timetuple().tm_yday
    # 1월 1일 부근 최저(-2℃), 8월 초 최고(28℃) → 평균 13, 진폭 15
    base = 13 - 15 * math.cos((day_of_year - 5) / 365 * 2 * math.pi)
    return round(base + random.gauss(0, 2.5), 1)


def main() -> None:
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        print(f"시드 기간: {START_DATE} ~ {END_DATE} ({(END_DATE - START_DATE).days + 1}일)")

        # 0) 멱등성: 기존 시드 거래/날씨 제거
        cur.execute("DELETE FROM material_doc_item")
        cur.execute("DELETE FROM material_doc_header")
        cur.execute("DELETE FROM ext_weather")
        cur.execute("DELETE FROM ext_holiday")
        cur.execute("UPDATE stock SET unrestricted_qty = 0")

        # 1) 기초재고 입고(561): 각 자재 초기 재고 충분히 확보
        cur.execute(
            "INSERT INTO material_doc_header (posting_date, source) VALUES (%s,'SEED') RETURNING doc_no",
            (START_DATE,),
        )
        gr_doc = cur.fetchone()[0]
        for i, (mat, p) in enumerate(MATERIALS.items(), start=1):
            qty = p["base"] * 120  # 약 4개월치 초기재고
            cur.execute(
                """INSERT INTO material_doc_item
                   (doc_no, item_no, material_no, plant_id, sloc_id, movement_type, quantity)
                   VALUES (%s,%s,%s,%s,%s,'561',%s)""",
                (gr_doc, i, mat, PLANT, p["sloc"], qty),
            )
            cur.execute(
                "UPDATE stock SET unrestricted_qty = unrestricted_qty + %s "
                "WHERE material_no=%s AND plant_id=%s AND sloc_id=%s",
                (qty, mat, PLANT, p["sloc"]),
            )

        # 2) 일자별 날씨 + 공휴일 + 출고
        weather_rows, holiday_rows = [], []
        d = START_DATE
        while d <= END_DATE:
            temp = seasonal_temp(d)
            tmin, tmax = round(temp - random.uniform(3, 6), 1), round(temp + random.uniform(3, 6), 1)
            precip = round(max(0, random.gauss(0, 6)), 1)
            weather_rows.append((d, "108", temp, tmin, tmax, precip))

            is_weekend = d.weekday() >= 5
            holiday_name = HOLIDAYS.get((d.month, d.day))
            if holiday_name:
                holiday_rows.append((d, holiday_name))

            # 출고 자재문서(201) 1건/일, 자재별 라인
            cur.execute(
                "INSERT INTO material_doc_header (posting_date, source) VALUES (%s,'SEED') RETURNING doc_no",
                (d,),
            )
            gi_doc = cur.fetchone()[0]
            for i, (mat, p) in enumerate(MATERIALS.items(), start=1):
                demand = p["base"] + p["temp_coef"] * (temp - 13)
                if is_weekend or holiday_name:
                    demand *= 1.25  # 주말·공휴일 수요 증가
                demand = max(0, demand + random.gauss(0, demand * 0.15))
                qty = int(round(demand))
                if qty <= 0:
                    continue
                cur.execute(
                    """INSERT INTO material_doc_item
                       (doc_no, item_no, material_no, plant_id, sloc_id, movement_type, quantity)
                       VALUES (%s,%s,%s,%s,%s,'201',%s)""",
                    (gi_doc, i, mat, PLANT, p["sloc"], qty),
                )
                cur.execute(
                    "UPDATE stock SET unrestricted_qty = GREATEST(unrestricted_qty - %s, 0) "
                    "WHERE material_no=%s AND plant_id=%s AND sloc_id=%s",
                    (qty, mat, PLANT, p["sloc"]),
                )
            d += timedelta(days=1)

        cur.executemany(
            "INSERT INTO ext_weather (obs_date, region_code, avg_temp, min_temp, max_temp, precip_mm) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            weather_rows,
        )
        cur.executemany(
            "INSERT INTO ext_holiday (holiday_date, name) VALUES (%s,%s)",
            holiday_rows,
        )

        # 3) 중간 보충 입고(101): 재고가 바닥나지 않도록 분기별 재입고
        d = START_DATE + timedelta(days=90)
        while d <= END_DATE:
            cur.execute(
                "INSERT INTO material_doc_header (posting_date, source) VALUES (%s,'SEED') RETURNING doc_no",
                (d,),
            )
            doc = cur.fetchone()[0]
            for i, (mat, p) in enumerate(MATERIALS.items(), start=1):
                qty = p["base"] * 90
                cur.execute(
                    """INSERT INTO material_doc_item
                       (doc_no, item_no, material_no, plant_id, sloc_id, movement_type, quantity)
                       VALUES (%s,%s,%s,%s,%s,'101',%s)""",
                    (doc, i, mat, PLANT, p["sloc"], qty),
                )
                cur.execute(
                    "UPDATE stock SET unrestricted_qty = unrestricted_qty + %s "
                    "WHERE material_no=%s AND plant_id=%s AND sloc_id=%s",
                    (qty, mat, PLANT, p["sloc"]),
                )
            d += timedelta(days=90)

        # 4) 재고 스냅샷 이력(이력성 엔터티): 월말 시점 재고를 누적 계산해 적재
        cur.execute("DELETE FROM stock_snapshot_history")
        # 자재별 누적 재고를 일자 순회하며 추적해 월말에 스냅샷
        cur.execute("""
            SELECT h.posting_date, i.material_no, i.plant_id, i.sloc_id,
                   i.quantity * m.direction AS signed_qty
            FROM material_doc_item i
            JOIN material_doc_header h ON h.doc_no = i.doc_no
            JOIN movement_type m ON m.code = i.movement_type
            ORDER BY h.posting_date
        """)
        running: dict[tuple, float] = {}
        snapshots: list[tuple] = []
        prev_month = None
        rows = cur.fetchall()
        # 일자별로 마지막 날 잔량을 월말 스냅샷으로 저장
        from collections import defaultdict
        by_date = defaultdict(list)
        for pdate, mat, pl, sl, sq in rows:
            by_date[pdate].append((mat, pl, sl, float(sq)))
        all_dates = sorted(by_date)
        for idx, dte in enumerate(all_dates):
            for mat, pl, sl, sq in by_date[dte]:
                key = (mat, pl, sl)
                running[key] = running.get(key, 0) + sq
            is_month_end = (idx + 1 == len(all_dates)) or (all_dates[idx + 1].month != dte.month)
            if is_month_end:
                for (mat, pl, sl), qty in running.items():
                    snapshots.append((dte, mat, pl, sl, max(qty, 0)))
        cur.executemany(
            "INSERT INTO stock_snapshot_history (snapshot_date, material_no, plant_id, sloc_id, unrestricted_qty) "
            "VALUES (%s,%s,%s,%s,%s)",
            snapshots,
        )

        conn.commit()
        print(f"재고 스냅샷 이력: {len(snapshots)}건")

        cur.execute("SELECT count(*) FROM material_doc_item")
        n_items = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM ext_weather")
        n_weather = cur.fetchone()[0]
        print(f"완료: 자재문서 항목 {n_items}건, 날씨 {n_weather}일, 공휴일 {len(holiday_rows)}건")


if __name__ == "__main__":
    main()
