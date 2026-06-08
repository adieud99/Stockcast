"""ORM 기반 시더 — 어떤 SQLAlchemy 세션(SQLite/PostgreSQL)에서도 동작.

psycopg 직접 연결(seed_transactions.py)과 달리, 이 시더는 ORM 세션만 받으므로
테스트·CI·로컬 데모에서 psql 없이도 동일한 데이터를 적재할 수 있다.
기온↔출고 상관(난방 음/냉방 양)을 동일하게 심는다.
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

# material_no, 설명, 그룹, sloc, base수요, 기온계수
MATERIALS = [
    ("100001", "전기 히터", "HEAT", "0002", 12, -0.9),
    ("100002", "온수 매트", "HEAT", "0002", 10, -0.7),
    ("100003", "핫팩 (50개입)", "HEAT", "0002", 25, -1.4),
    ("200001", "선풍기", "COOL", "0002", 11, 0.8),
    ("200002", "휴대용 미니선풍기", "COOL", "0002", 18, 1.1),
    ("300001", "생수 2L (6입)", "BEV", "0001", 40, 0.3),
    ("300002", "물티슈", "DAILY", "0001", 30, 0.0),
]
GROUPS = [("HEAT", "난방용품"), ("COOL", "냉방용품"),
          ("DAILY", "생활필수품"), ("BEV", "음료")]


def _temp(d: date, rnd: random.Random) -> float:
    doy = d.timetuple().tm_yday
    return round(13 - 15 * math.cos((doy - 5) / 365 * 2 * math.pi) + rnd.gauss(0, 2.5), 1)


def seed_master(db: Session) -> None:
    db.add(Plant(plant_id="1000", name="서울 본사 물류센터"))
    db.add_all([
        StorageLocation(plant_id="1000", sloc_id="0001", name="상온 창고"),
        StorageLocation(plant_id="1000", sloc_id="0002", name="시즌 상품 창고"),
    ])
    db.add_all([MaterialGroup(group_code=c, name=n) for c, n in GROUPS])
    db.add_all([
        MovementType(code="101", description="입고 (구매 입고)", direction=1),
        MovementType(code="201", description="출고 (소비/판매)", direction=-1),
        MovementType(code="561", description="기초재고 입고", direction=1),
    ])
    for i, (mno, desc, grp, sloc, *_ ) in enumerate(MATERIALS):
        db.add(Material(material_no=mno, description=desc, material_type="HAWA",
                        group_code=grp, base_uom="EA"))
        db.add(Stock(material_no=mno, plant_id="1000", sloc_id=sloc, unrestricted_qty=0))
        db.add(NfcTag(tag_uid=f"04:A1:B2:C3:D4:{i+1:02d}", material_no=mno,
                      plant_id="1000", sloc_id=sloc))
    db.commit()


def seed_transactions(db: Session, days: int = 365, seed: int = 42) -> dict:
    rnd = random.Random(seed)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    stock = {(m[0], "1000", m[3]): 0.0 for m in MATERIALS}

    # 기초재고(561)
    h0 = MaterialDocHeader(posting_date=start, source="SEED"); db.add(h0); db.flush()
    for i, (mno, _d, _g, sloc, base, _c) in enumerate(MATERIALS, 1):
        qty = base * 120
        db.add(MaterialDocItem(doc_no=h0.doc_no, item_no=i, material_no=mno,
               plant_id="1000", sloc_id=sloc, movement_type="561", quantity=qty))
        stock[(mno, "1000", sloc)] += qty

    snaps = 0
    d = start
    while d <= end:
        t = _temp(d, rnd)
        db.add(ExtWeather(obs_date=d, region_code="108", avg_temp=t,
                          min_temp=round(t - rnd.uniform(3, 6), 1),
                          max_temp=round(t + rnd.uniform(3, 6), 1),
                          precip_mm=round(max(0, rnd.gauss(0, 6)), 1)))
        hol = HOLIDAYS.get((d.month, d.day))
        if hol:
            db.add(ExtHoliday(holiday_date=d, name=hol))
        # 분기마다 보충입고(101): 재고가 바닥나지 않도록
        if (d - start).days > 0 and (d - start).days % 90 == 0:
            hr = MaterialDocHeader(posting_date=d, source="SEED"); db.add(hr); db.flush()
            for j, (mno, _d2, _g2, sloc2, base2, _c2) in enumerate(MATERIALS, 1):
                qty2 = base2 * 90
                db.add(MaterialDocItem(doc_no=hr.doc_no, item_no=j, material_no=mno,
                       plant_id="1000", sloc_id=sloc2, movement_type="101", quantity=qty2))
                stock[(mno, "1000", sloc2)] += qty2
        wk = d.weekday() >= 5
        h = MaterialDocHeader(posting_date=d, source="SEED"); db.add(h); db.flush()
        for i, (mno, _d, _g, sloc, base, coef) in enumerate(MATERIALS, 1):
            dem = base + coef * (t - 13)
            if wk or hol:
                dem *= 1.25
            dem = max(0, dem + rnd.gauss(0, dem * 0.15))
            qty = int(round(dem))
            if qty <= 0:
                continue
            db.add(MaterialDocItem(doc_no=h.doc_no, item_no=i, material_no=mno,
                   plant_id="1000", sloc_id=sloc, movement_type="201", quantity=qty))
            stock[(mno, "1000", sloc)] = max(0, stock[(mno, "1000", sloc)] - qty)
        # 월말 스냅샷
        nxt = d + timedelta(days=1)
        if nxt > end or nxt.month != d.month:
            for (mno, pl, sloc), q in stock.items():
                db.add(StockSnapshotHistory(snapshot_date=d, material_no=mno,
                       plant_id=pl, sloc_id=sloc, unrestricted_qty=q))
                snaps += 1
        d += timedelta(days=1)

    # 최종 재고 반영
    for (mno, pl, sloc), q in stock.items():
        st = db.get(Stock, (mno, pl, sloc))
        st.unrestricted_qty = q
    db.commit()
    return {"days": days, "snapshots": snaps}


def seed_all(db: Session, days: int = 365) -> dict:
    seed_master(db)
    return seed_transactions(db, days=days)
