"""ORM 기반 시더 — 어떤 SQLAlchemy 세션(SQLite/PostgreSQL/Oracle)에서도 동작.

업종: 패션·의류 유통 물류센터.
수요 신호: 기온(겨울 아우터↑/여름 상의↑) + 강수(우산·레인코트↑) + 주말·공휴일.
→ 회귀·시계열 예측이 잡아낼 신호를 의도적으로 심는다.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.mm import (
    ExtHoliday, ExtWeather, Material, MaterialDocHeader, MaterialDocItem,
    MaterialGroup, MovementType, NfcTag, Plant, Stock, StockSnapshotHistory,
    StorageLocation,
)

HOLIDAYS = {(1, 1): "신정", (3, 1): "삼일절", (5, 5): "어린이날",
            (6, 6): "현충일", (8, 15): "광복절", (10, 3): "개천절",
            (10, 9): "한글날", (12, 25): "성탄절"}

GROUPS = [("OUTER", "아우터"), ("TOP", "상의"),
          ("BOTTOM", "하의"), ("ACC", "잡화")]

# material_no, 상품명, 그룹, 저장위치, 일평균수요, 기온계수, 강수계수
MATERIALS = [
    # 아우터 — 겨울(기온↓ 수요↑)
    ("100001", "경량 패딩 점퍼",     "OUTER",  "0002", 15, -1.1, 0.0),
    ("100002", "울 블렌드 코트",      "OUTER",  "0002", 10, -0.8, 0.0),
    ("100003", "롱 구스다운 점퍼",    "OUTER",  "0002",  8, -1.0, 0.0),
    ("100004", "플리스 집업",         "OUTER",  "0002", 16, -0.9, 0.0),
    ("100005", "무스탕 자켓",         "OUTER",  "0002",  5, -0.7, 0.0),
    # 상의 — 겨울
    ("110001", "기모 후드 집업",      "TOP",    "0002", 20, -1.0, 0.0),
    ("110002", "울 니트 스웨터",      "TOP",    "0002", 18, -0.9, 0.0),
    ("110003", "터틀넥 니트",         "TOP",    "0002", 14, -0.8, 0.0),
    ("110004", "기모 맨투맨",         "TOP",    "0002", 22, -0.9, 0.0),
    # 상의 — 여름(기온↑ 수요↑)
    ("200001", "코튼 반팔 티셔츠",    "TOP",    "0001", 30,  1.2, 0.0),
    ("200002", "린넨 셔츠",           "TOP",    "0001", 14,  0.7, 0.0),
    ("200003", "슬리브리스 탑",       "TOP",    "0001", 12,  0.9, 0.0),
    ("200004", "폴로 피케 셔츠",      "TOP",    "0001", 16,  0.6, 0.0),
    # 하의
    ("210001", "코튼 치노 반바지",    "BOTTOM", "0001", 16,  0.9, 0.0),
    ("210002", "데님 청바지",         "BOTTOM", "0001", 24,  0.0, 0.0),
    ("210003", "슬랙스",             "BOTTOM", "0001", 18,  0.0, 0.0),
    ("210004", "조거 팬츠",           "BOTTOM", "0001", 20, -0.3, 0.0),
    ("210005", "기모 트레이닝 팬츠",  "BOTTOM", "0002", 15, -0.7, 0.0),
    # 잡화 — 우천(강수↑ 수요↑)
    ("300001", "3단 자동 장우산",     "ACC",    "0001",  8,  0.0, 1.5),
    ("300002", "경량 레인코트",       "ACC",    "0002",  6, -0.2, 1.2),
    ("300003", "방수 우비",           "ACC",    "0001",  5,  0.0, 1.3),
    # 잡화 — 겨울
    ("310001", "니트 비니",           "ACC",    "0002", 12, -0.6, 0.0),
    ("310002", "기모 장갑",           "ACC",    "0002", 10, -0.7, 0.0),
    ("310003", "머플러 목도리",       "ACC",    "0002", 11, -0.8, 0.0),
    # 잡화 — 여름
    ("320001", "버킷햇",             "ACC",    "0001", 14,  0.5, 0.0),
    ("320002", "캔버스 토트백",       "ACC",    "0001", 13,  0.0, 0.0),
    # 상시(대조군 — 날씨 무관)
    ("400001", "베이직 양말 5족",     "ACC",    "0001", 25,  0.0, 0.0),
    ("400002", "베이직 무지 티셔츠",  "TOP",    "0001", 22,  0.0, 0.0),
    ("400003", "베이직 무지 후드티",  "TOP",    "0001", 20,  0.0, 0.0),
]
PLANT = "1000"
REF_TEMP = 15.0


def _temp(d: date, rnd: random.Random) -> float:
    doy = d.timetuple().tm_yday
    return round(13 - 15 * math.cos((doy - 5) / 365 * 2 * math.pi) + rnd.gauss(0, 2.5), 1)


def seed_master(db: Session) -> None:
    db.add(Plant(plant_id=PLANT, name="수도권 의류 물류센터"))
    db.add_all([
        StorageLocation(plant_id=PLANT, sloc_id="0001", name="상시 상품 창고"),
        StorageLocation(plant_id=PLANT, sloc_id="0002", name="시즌 상품 창고"),
    ])
    db.add_all([MaterialGroup(group_code=c, name=n) for c, n in GROUPS])
    db.add_all([
        MovementType(code="101", description="입고 (구매 입고)", direction=1),
        MovementType(code="201", description="출고 (판매 출고)", direction=-1),
        MovementType(code="561", description="기초재고 입고", direction=1),
    ])
    for i, (mno, desc, grp, sloc, *_rest) in enumerate(MATERIALS):
        db.add(Material(material_no=mno, description=desc, material_type="HAWA",
                        group_code=grp, base_uom="EA"))
        db.add(Stock(material_no=mno, plant_id=PLANT, sloc_id=sloc, unrestricted_qty=0))
        db.add(NfcTag(tag_uid=f"04:A1:B2:C3:D4:{i+1:02d}", material_no=mno,
                      plant_id=PLANT, sloc_id=sloc))
    db.commit()


def seed_transactions(db: Session, days: int = 365, seed: int = 42) -> dict:
    rnd = random.Random(seed)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    stock = {(m[0], PLANT, m[3]): 0.0 for m in MATERIALS}

    h0 = MaterialDocHeader(posting_date=start, source="SEED"); db.add(h0); db.flush()
    for i, (mno, _d, _g, sloc, base, *_c) in enumerate(MATERIALS, 1):
        qty = base * 120
        db.add(MaterialDocItem(doc_no=h0.doc_no, item_no=i, material_no=mno,
               plant_id=PLANT, sloc_id=sloc, movement_type="561", quantity=qty))
        stock[(mno, PLANT, sloc)] += qty

    snaps = 0
    d = start
    while d <= end:
        t = _temp(d, rnd)
        precip = round(max(0, rnd.gauss(0, 6)), 1)
        db.add(ExtWeather(obs_date=d, region_code="108", avg_temp=t,
                          min_temp=round(t - rnd.uniform(3, 6), 1),
                          max_temp=round(t + rnd.uniform(3, 6), 1),
                          precip_mm=precip))
        hol = HOLIDAYS.get((d.month, d.day))
        if hol:
            db.add(ExtHoliday(holiday_date=d, name=hol))
        if (d - start).days > 0 and (d - start).days % 90 == 0:
            hr = MaterialDocHeader(posting_date=d, source="SEED"); db.add(hr); db.flush()
            for j, (mno, _d2, _g2, sloc2, base2, *_c2) in enumerate(MATERIALS, 1):
                qty2 = base2 * 90
                db.add(MaterialDocItem(doc_no=hr.doc_no, item_no=j, material_no=mno,
                       plant_id=PLANT, sloc_id=sloc2, movement_type="101", quantity=qty2))
                stock[(mno, PLANT, sloc2)] += qty2
        wk = d.weekday() >= 5
        h = MaterialDocHeader(posting_date=d, source="SEED"); db.add(h); db.flush()
        for i, (mno, _d, _g, sloc, base, tc, pc) in enumerate(MATERIALS, 1):
            dem = base + tc * (t - REF_TEMP) + pc * precip
            if wk or hol:
                dem *= 1.3
            dem = max(0, dem + rnd.gauss(0, max(dem, 1) * 0.15))
            qty = int(round(dem))
            if qty <= 0:
                continue
            db.add(MaterialDocItem(doc_no=h.doc_no, item_no=i, material_no=mno,
                   plant_id=PLANT, sloc_id=sloc, movement_type="201", quantity=qty))
            stock[(mno, PLANT, sloc)] = max(0, stock[(mno, PLANT, sloc)] - qty)
        nxt = d + timedelta(days=1)
        if nxt > end or nxt.month != d.month:
            for (mno, pl, sloc), q in stock.items():
                db.add(StockSnapshotHistory(snapshot_date=d, material_no=mno,
                       plant_id=pl, sloc_id=sloc, unrestricted_qty=q))
                snaps += 1
        d += timedelta(days=1)

    for (mno, pl, sloc), q in stock.items():
        st = db.get(Stock, (mno, pl, sloc))
        st.unrestricted_qty = q
    db.commit()
    return {"days": days, "snapshots": snaps}


def seed_all(db: Session, days: int = 365) -> dict:
    seed_master(db)
    return seed_transactions(db, days=days)
