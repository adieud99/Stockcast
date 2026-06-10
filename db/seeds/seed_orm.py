"""ORM 기반 시더 — SQLite/PostgreSQL/Oracle 공통.

업종: 공공조달 납품업체(B2G) 물류센터.
수요 신호: 기온(겨울 제설·난방↑/여름 냉방·제초↑) + 강수(우의·제설↑) + 주말·공휴일.
판매단가(unit_price) 포함 → 재고자산금액·ABC분석 등 경영지표 산출.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.mm import (
    ExtHoliday, ExtWeather, Material, MaterialDocHeader, MaterialDocItem,
    MaterialGroup, MovementType, NfcTag, Plant, Stock, StockSnapshotHistory,
    StorageLocation,
)

HOLIDAYS = {(1, 1): "신정", (3, 1): "삼일절", (5, 5): "어린이날",
            (6, 6): "현충일", (8, 15): "광복절", (10, 3): "개천절",
            (10, 9): "한글날", (12, 25): "성탄절"}

GROUPS = [("DEICE", "제설·방재"), ("SAFETY", "안전·보호구"),
          ("HVAC", "냉난방"), ("OFFICE", "사무용품"),
          ("CLEAN", "청소·위생"), ("HEALTH", "방역·보건"),
          ("GARDEN", "제초·조경"), ("ELEC", "전기·조명")]

# material_no, 상품명, 그룹, 저장위치, 일평균수요, 기온계수, 강수계수, 판매단가(원)
MATERIALS = [
    # 제설·방재 (겨울·강설 수요 ↑)
    ("100001", "친환경 제설제(염화칼슘) 25kg", "DEICE",  "0002", 10, -1.6, 0.8,  15000),
    ("100002", "제설용 알루미늄 삽",          "DEICE",  "0002",  6, -0.8, 0.0,  13000),
    ("100003", "동절기 모래주머니 20kg",       "DEICE",  "0002",  7, -0.7, 0.5,   3000),
    ("100004", "친환경 제설제(염화마그네슘) 20kg","DEICE", "0002", 8, -1.4, 0.7,  22000),
    # 안전·보호구
    ("110001", "작업용 안전화",                "SAFETY", "0001", 14,  0.0, 0.0,  45000),
    ("110002", "산업용 안전모",                "SAFETY", "0001", 16,  0.0, 0.0,   8000),
    ("110003", "산업용 안전장갑(12켤레)",       "SAFETY", "0001", 22,  0.0, 0.0,  12000),
    ("110004", "방한 안전작업복",              "SAFETY", "0002", 12, -0.9, 0.0,  89000),
    ("110005", "산업용 우의(레인코트)",         "SAFETY", "0001", 10, -0.2, 1.4,  18000),
    ("110006", "야광 안전조끼",                "SAFETY", "0001", 18,  0.0, 0.0,   9000),
    ("110007", "안전 고깔(라바콘)",            "SAFETY", "0001", 15,  0.0, 0.0,  11000),
    # 냉난방 (계절 수요)
    ("120001", "산업용 선풍기",                "HVAC",   "0002",  9,  1.1, 0.0,  95000),
    ("120002", "전기 온풍기",                  "HVAC",   "0002",  7, -1.0, 0.0,  78000),
    ("120003", "산업용 전기히터",              "HVAC",   "0002",  6, -1.1, 0.0, 145000),
    ("120004", "이동식 에어컨",                "HVAC",   "0002",  5,  1.0, 0.0, 320000),
    # 사무용품 (계절 무관·통제군)
    ("130001", "A4 복사용지(2500매 박스)",     "OFFICE", "0001", 30,  0.0, 0.0,  28000),
    ("130002", "토너 카트리지",                "OFFICE", "0001", 16,  0.0, 0.0,  65000),
    ("130003", "파일박스 세트",                "OFFICE", "0001", 20,  0.0, 0.0,   9000),
    # 청소·위생
    ("140001", "다목적 세정제(5L 말통)",        "CLEAN",  "0001", 18,  0.0, 0.0,  14000),
    ("140002", "화장지(30롤 박스)",            "CLEAN",  "0001", 25,  0.0, 0.0,  22000),
    ("140003", "분리수거함(3분류)",            "CLEAN",  "0001",  8,  0.0, 0.0,  35000),
    ("140004", "산업용 대걸레 세트",            "CLEAN",  "0001", 12,  0.0, 0.0,  16000),
    # 방역·보건
    ("150001", "손 소독제(5L 말통)",           "HEALTH", "0001", 16,  0.3, 0.0,  19000),
    ("150002", "KF94 마스크(50매 박스)",       "HEALTH", "0001", 20,  0.0, 0.0,  32000),
    ("150003", "일회용 방역복",                "HEALTH", "0001", 10,  0.0, 0.0,  12000),
    # 제초·조경 (여름 수요 ↑)
    ("160001", "제초제(5L 말통)",              "GARDEN", "0002",  9,  0.9, 0.0,  28000),
    ("160002", "예초기 날 세트",               "GARDEN", "0002",  8,  0.7, 0.0,   9500),
    ("160003", "원예용 모종삽",                "GARDEN", "0001", 11,  0.5, 0.0,   4500),
    # 전기·조명
    ("170001", "LED 투광등",                   "ELEC",   "0001", 14,  0.0, 0.0,  42000),
    ("170002", "산업용 멀티탭",                "ELEC",   "0001", 17,  0.0, 0.0,  15000),
]
PLANT = "1000"
REF_TEMP = 15.0


def _temp(d: date, rnd: random.Random) -> float:
    doy = d.timetuple().tm_yday
    return round(13 - 15 * math.cos((doy - 5) / 365 * 2 * math.pi) + rnd.gauss(0, 2.5), 1)


def seed_master(db: Session) -> None:
    db.add(Plant(plant_id=PLANT, name="공공조달 납품물류센터"))
    db.add_all([
        StorageLocation(plant_id=PLANT, sloc_id="0001", name="상시 품목 창고"),
        StorageLocation(plant_id=PLANT, sloc_id="0002", name="계절 품목 창고"),
    ])
    db.add_all([MaterialGroup(group_code=c, name=n) for c, n in GROUPS])
    db.add_all([
        MovementType(code="101", description="입고 (구매 입고)", direction=1),
        MovementType(code="201", description="출고 (판매 출고)", direction=-1),
        MovementType(code="561", description="기초재고 입고", direction=1),
    ])
    # 마스터·룩업(부모) 테이블을 먼저 flush 해야 자재 INSERT 시 FK 위반이 없다.
    db.flush()
    for i, (mno, desc, grp, sloc, base, tc, pc, price) in enumerate(MATERIALS):
        db.add(Material(material_no=mno, description=desc, material_type="HAWA",
                        group_code=grp, base_uom="EA", unit_price=price))
        db.add(Stock(material_no=mno, plant_id=PLANT, sloc_id=sloc, unrestricted_qty=0))
        db.add(NfcTag(tag_uid=f"04:A1:B2:C3:D4:{i+1:02d}", material_no=mno,
                      plant_id=PLANT, sloc_id=sloc))
    db.commit()


def seed_transactions(db: Session, days: int = 365, seed: int = 42,
                      use_real_weather: bool = False) -> dict:
    rnd = random.Random(seed)
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    stock = {(m[0], PLANT, m[3]): 0.0 for m in MATERIALS}

    h0 = MaterialDocHeader(posting_date=start, source="SEED"); db.add(h0); db.flush()
    for i, (mno, _d, _g, sloc, base, *_rest) in enumerate(MATERIALS, 1):
        qty = base * 120
        db.add(MaterialDocItem(doc_no=h0.doc_no, item_no=i, material_no=mno,
               plant_id=PLANT, sloc_id=sloc, movement_type="561", quantity=qty))
        stock[(mno, PLANT, sloc)] += qty

    # 실 공공데이터 모드: DB에 적재된 기상청 날씨·공휴일을 읽어 수요에 반영
    wmap, holset = {}, {}
    if use_real_weather:
        for w in db.scalars(select(ExtWeather)).all():
            wmap[w.obs_date] = (
                float(w.avg_temp) if w.avg_temp is not None else None,
                float(w.precip_mm) if w.precip_mm is not None else 0.0,
            )
        for hday in db.scalars(select(ExtHoliday)).all():
            holset[hday.holiday_date] = hday.name
        miss = sum(1 for i in range(days) if (start + timedelta(days=i)) not in wmap)
        print(f"   실데이터 모드 — 날씨 {len(wmap)}일, 공휴일 {len(holset)}일 "
              f"(날씨 누락 {miss}일은 합성 보정)")

    snaps = 0
    d = start
    while d <= end:
        if use_real_weather:
            wt = wmap.get(d)
            if wt and wt[0] is not None:
                t, precip = wt[0], wt[1]
            else:  # 실데이터 누락일은 계절 모형으로 보정
                t = _temp(d, rnd)
                precip = round(max(0, rnd.gauss(0, 6)), 1)
            hol = holset.get(d) or HOLIDAYS.get((d.month, d.day))
        else:
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
            for j, (mno, _d2, _g2, sloc2, base2, *_r2) in enumerate(MATERIALS, 1):
                qty2 = base2 * 90
                db.add(MaterialDocItem(doc_no=hr.doc_no, item_no=j, material_no=mno,
                       plant_id=PLANT, sloc_id=sloc2, movement_type="101", quantity=qty2))
                stock[(mno, PLANT, sloc2)] += qty2
        wk = d.weekday() >= 5
        h = MaterialDocHeader(posting_date=d, source="SEED"); db.add(h); db.flush()
        for i, (mno, _d, _g, sloc, base, tc, pc, _price) in enumerate(MATERIALS, 1):
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


def seed_all(db: Session, days: int = 365, use_real_weather: bool = False) -> dict:
    seed_master(db)
    return seed_transactions(db, days=days, use_real_weather=use_real_weather)
