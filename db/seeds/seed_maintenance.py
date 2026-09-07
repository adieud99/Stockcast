"""설비와 1년치 정비 이력을 만드는 시더.

가동률이나 PM준수율, MTTR 같은 지표는 정상만 있는 데이터로는 아무 의미가 없다.
그래서 PM이 밀린 설비, 고장으로 멈춘 설비, 아직 안 끝난 오더를 일부러 섞는다.

정비 완료 시 사용 부품은 실제 MM 전기(이동유형 261)를 태워 재고를 뺀다.
시드로 만든 데이터도 자재문서 감사추적을 그대로 통과해야 하니까.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.maintenance import Equipment, MaintenanceOrder, MaintenanceOrderPart
from app.models.mm import Material, Stock
from app.schemas.movement import GoodsMovementCreate, GoodsMovementLine
from app.services.inventory import post_goods_movement
from app.services.maintenance import MVT_MAINTENANCE_ISSUE, ensure_movement_type

PLANT = "1000"

# equipment_no, 설비명, 분류, 저장위치, 제조사, 사용연수, PM주기(일), 초기상태
EQUIPMENTS = [
    ("EQ-1001", "전동 지게차 2.5t (1호기)", "하역", "0001", "클라크",  4, 90,  "RUN"),
    ("EQ-1002", "전동 지게차 2.5t (2호기)", "하역", "0001", "클라크",  6, 90,  "RUN"),
    ("EQ-1003", "리치트럭 1.5t",            "하역", "0002", "토요타",  3, 120, "RUN"),
    ("EQ-1004", "도크 레벨러 A",            "하역", "0001", "한성물류", 8, 180, "RUN"),
    ("EQ-2001", "롤러 컨베이어 라인 A",      "반송", "0001", "대성기계", 5, 60,  "RUN"),
    ("EQ-2002", "롤러 컨베이어 라인 B",      "반송", "0001", "대성기계", 5, 60,  "CHECK"),
    ("EQ-2003", "자동 소터(분류기)",         "반송", "0001", "한독시스템", 2, 90, "RUN"),
    ("EQ-3001", "항온항습기 (상온창고)",     "공조", "0001", "캐리어",   7, 120, "RUN"),
    ("EQ-3002", "냉동 유닛 (계절품목창고)",   "공조", "0002", "LG전자",   4, 90,  "DOWN"),
    ("EQ-4001", "스트레치 랩핑기",           "포장", "0001", "삼성포장", 6, 120, "RUN"),
    ("EQ-4002", "자동 테이핑기",             "포장", "0001", "삼성포장", 9, 180, "RUN"),
    ("EQ-5001", "비상 발전기 100kW",         "전기", "0001", "두산",     10, 180, "RUN"),
    ("EQ-5002", "지게차 충전 스테이션",       "전기", "0001", "LS일렉트릭", 4, 180, "RUN"),
    ("EQ-6001", "스프링클러 가압펌프",        "방재", "0001", "우진펌프", 12, 365, "RUN"),
]

# 정비에 쓰는 소모 부품. 기존 자재 마스터에서 골랐다
PART_POOL = ["110003", "110002", "140001", "170002", "170001", "130003"]

# 고장(CM) 사유. 물류센터에서 자주 나오는 것들로 채웠다
CM_TITLES = [
    "유압 실린더 오일 누유", "배터리 충전 불량", "구동 벨트 파손",
    "베어링 이상 소음", "제어반 릴레이 접점 불량", "냉매 누설로 온도 미달",
    "센서 오작동으로 라인 정지", "감속기 기어 마모",
]
PM_TITLES = {
    "하역": "정기 점검 — 유압·타이어·배터리",
    "반송": "정기 점검 — 벨트 장력·롤러 윤활",
    "공조": "정기 점검 — 필터 교체·냉매압 확인",
    "포장": "정기 점검 — 히터·커터날 점검",
    "전기": "정기 점검 — 절연저항·단자 조임",
    "방재": "정기 점검 — 펌프 기동시험·압력 확인",
}


def _stock_location(db: Session, material_no: str, qty: float) -> str | None:
    """그 부품을 실제로 꺼낼 수 있는 저장위치를 찾는다.

    예비부품은 설비가 놓인 창고가 아니라 부품이 쌓인 창고에서 나간다. 설비
    위치로만 찾으면 재고가 없어서 전기를 건너뛰게 되고, 그러면 완료됐는데
    자재문서가 없는 상태(정합성 점검 C07 위반)가 만들어진다.
    """
    for st in db.scalars(select(Stock).where(Stock.material_no == material_no)).all():
        if float(st.unrestricted_qty) > qty:
            return st.sloc_id
    return None


def _consume_parts(db: Session, order: MaintenanceOrder,
                   candidates: list[tuple[str, int]], posting_date: date) -> int:
    """실제로 뺄 수 있는 부품만 오더에 등록하고 이동유형 261로 전기한다.

    등록은 했는데 전기를 못 한 상태를 만들지 않는 게 중요하다. 완료된 오더의
    부품은 반드시 자재문서를 갖는다는 규칙을 시드 데이터도 지켜야 한다.
    """
    lines, picked = [], []
    for mno, qty in candidates:
        sloc = _stock_location(db, mno, qty)
        if not sloc:
            continue                      # 어디에도 재고가 없으면 그 부품은 안 쓴다
        picked.append((mno, qty))
        lines.append(GoodsMovementLine(
            material_no=mno, plant_id=PLANT, sloc_id=sloc,
            movement_type=MVT_MAINTENANCE_ISSUE, quantity=Decimal(qty)))
    if not lines:
        return 0

    for i, (mno, qty) in enumerate(picked, start=1):
        db.add(MaintenanceOrderPart(order_no=order.order_no, item_no=i,
                                    material_no=mno, quantity=qty))
    db.flush()
    result = post_goods_movement(
        db, GoodsMovementCreate(posting_date=posting_date, source="PM", lines=lines))
    for p in order.parts:
        p.posted_doc_no = result.doc_no
    return len(picked)


def seed_maintenance(db: Session, days: int = 365, seed: int = 7) -> dict:
    """설비 + 정비 이력 적재. 이미 설비가 있으면 건너뛴다(멱등)."""
    if db.scalar(select(Equipment).limit(1)):
        return {"skipped": "설비 데이터가 이미 존재"}

    ensure_movement_type(db)
    rnd = random.Random(seed)
    today = date.today()

    # 부품 후보는 실제로 마스터에 있는 것만 사용(FK 위반 방지)
    known = {m.material_no for m in db.scalars(select(Material)).all()}
    parts_pool = [m for m in PART_POOL if m in known]

    for eno, name, cat, sloc, maker, age_y, cycle, st in EQUIPMENTS:
        db.add(Equipment(
            equipment_no=eno, name=name, category=cat,
            plant_id=PLANT, sloc_id=sloc, manufacturer=maker,
            install_date=today - timedelta(days=age_y * 365 + rnd.randint(0, 300)),
            status=st, pm_cycle_days=cycle, last_pm_date=None))
    db.commit()

    n_pm = n_cm = n_open = 0

    # ── 1) 예방정비(PM) 이력 — 주기마다 한 건씩 과거로 거슬러 생성 ──
    for eq in db.scalars(select(Equipment)).all():
        if not eq.pm_cycle_days:
            continue
        # 마지막 PM을 주기보다 늦게 잡아서 일부 설비를 지연 상태로 만든다
        overdue = rnd.random() < 0.25
        offset = eq.pm_cycle_days + rnd.randint(5, 40) if overdue else rnd.randint(0, eq.pm_cycle_days - 1)
        last_done = today - timedelta(days=offset)

        d = last_done
        while (today - d).days <= days:
            planned = d + timedelta(days=rnd.randint(-2, 2))
            o = MaintenanceOrder(
                equipment_no=eq.equipment_no, order_type="PM", status="DONE",
                priority="M", title=PM_TITLES.get(eq.category, "정기 점검"),
                description=f"{eq.name} 정기 예방정비 ({eq.pm_cycle_days}일 주기)",
                requester="설비팀", request_date=planned - timedelta(days=3),
                planned_date=planned, completed_date=d,
                labor_cost=Decimal(rnd.choice([80000, 120000, 150000, 200000])))
            db.add(o)
            db.flush()
            chosen = [(rnd.choice(parts_pool), rnd.randint(1, 3))] if parts_pool else []
            _consume_parts(db, o, chosen, d)
            n_pm += 1
            d -= timedelta(days=eq.pm_cycle_days)

        eq.last_pm_date = last_done
    db.commit()

    # ── 2) 사후정비(CM) 이력 — 무작위 고장 ──
    eqs = db.scalars(select(Equipment)).all()
    for _ in range(18):
        eq = rnd.choice(eqs)
        req = today - timedelta(days=rnd.randint(10, days))
        # MTTR이 의미 있게 나오게 수리 소요일을 1~6일로 흩뿌린다
        done = req + timedelta(days=rnd.randint(1, 6))
        o = MaintenanceOrder(
            equipment_no=eq.equipment_no, order_type="CM", status="DONE",
            priority=rnd.choice(["H", "H", "M"]), title=rnd.choice(CM_TITLES),
            description=f"{eq.name} 고장 수리", requester="현장반장",
            request_date=req, planned_date=req + timedelta(days=1),
            completed_date=done,
            labor_cost=Decimal(rnd.choice([150000, 250000, 400000, 600000])))
        db.add(o)
        db.flush()
        chosen = [(rnd.choice(parts_pool), rnd.randint(1, 4))] if parts_pool else []
        _consume_parts(db, o, chosen, done)
        n_cm += 1
    db.commit()

    # ── 3) 지금 열려 있는 오더. 화면에 처리할 일이 보여야 한다 ──
    down_eq = [e for e in eqs if e.status == "DOWN"]
    check_eq = [e for e in eqs if e.status == "CHECK"]
    open_specs = []
    if down_eq:
        open_specs.append((down_eq[0], "CM", "WIP", "H", "냉매 누설로 온도 미달", 2))
    if check_eq:
        open_specs.append((check_eq[0], "PM", "WIP", "M", "정기 점검 — 벨트 장력·롤러 윤활", 1))
    open_specs.append((eqs[0], "PM", "REQ", "M", "정기 점검 — 유압·타이어·배터리", 5))
    open_specs.append((eqs[4], "CM", "REQ", "H", "베어링 이상 소음", -3))  # 예정일 초과 = 지연

    for eq, otype, ostatus, prio, title, plan_in in open_specs:
        o = MaintenanceOrder(
            equipment_no=eq.equipment_no, order_type=otype, status=ostatus,
            priority=prio, title=title, description=f"{eq.name} — 처리 대기",
            requester="현장반장", request_date=today - timedelta(days=rnd.randint(1, 7)),
            planned_date=today + timedelta(days=plan_in))
        db.add(o)
        db.flush()
        if parts_pool:
            db.add(MaintenanceOrderPart(order_no=o.order_no, item_no=1,
                                        material_no=rnd.choice(parts_pool), quantity=2))
        n_open += 1
    db.commit()

    return {"equipment": len(EQUIPMENTS), "pm_orders": n_pm,
            "cm_orders": n_cm, "open_orders": n_open}
