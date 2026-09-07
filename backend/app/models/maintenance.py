"""
설비 유지보수 ORM 모델. SAP PM 모듈 구조를 차용했다.

재고 시스템에 설비 관리를 넣은 건, 물류센터에서 지게차나 컨베이어가 멈추면
입출고 처리량이 그대로 멈추기 때문이다. 설비 가동률이 재고 회전의 선행지표인
셈이라 물건 재고와 설비 상태를 같은 화면에서 봐야 한다고 봤다.

MM과 이어지는 지점이 하나 있다. 정비오더를 완료하면 사용한 부품이 이동유형
261로 자재문서에 전기돼서 재고가 실제로 줄어든다. SAP에서 PM 오더가 MM 재고를
소비하는 구조와 같다.

컬럼 옆 주석의 대문자는 대응되는 SAP PM 필드명이다.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Integer, Numeric, String, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# mm.py와 동일 규칙: PostgreSQL은 BIGSERIAL, SQLite(테스트)는 INTEGER 자동증가
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

# 설비 상태 코드. 가동률은 이 값으로 계산한다
EQUIPMENT_STATUS = {
    "RUN": "정상 가동",
    "CHECK": "점검 중",
    "DOWN": "고장 정지",
    "SCRAP": "폐기",
}

# 정비 유형. PM(예방) 비중이 높을수록 관리가 잘 되는 조직이다
ORDER_TYPE = {"PM": "예방정비", "CM": "사후정비"}

# 정비오더 진행 상태
ORDER_STATUS = {"REQ": "요청", "WIP": "진행", "DONE": "완료", "CANCEL": "취소"}


class Equipment(Base):          # EQUI + EQKT
    """설비 마스터. 물류센터가 가진 정비 대상 자산."""
    __tablename__ = "equipment"
    equipment_no: Mapped[str] = mapped_column(String(18), primary_key=True)   # EQUNR
    name: Mapped[str] = mapped_column(String(120))                           # EQKTX
    category: Mapped[str] = mapped_column(String(20))        # 하역/반송/공조/포장/전기
    plant_id: Mapped[str] = mapped_column(String(4))                         # WERKS
    sloc_id: Mapped[str] = mapped_column(String(4))                          # LGORT
    manufacturer: Mapped[str | None] = mapped_column(String(60))
    install_date: Mapped[date | None] = mapped_column(Date)                  # INBDT 설치일
    status: Mapped[str] = mapped_column(String(6), default="RUN")
    # 예방정비 주기(일). 0이면 PM 대상이 아니라 지연 판정에서 뺀다.
    pm_cycle_days: Mapped[int] = mapped_column(Integer, default=0)
    last_pm_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    orders: Mapped[list["MaintenanceOrder"]] = relationship(
        back_populates="equipment", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("status IN ('RUN','CHECK','DOWN','SCRAP')"),
        CheckConstraint("pm_cycle_days >= 0"),
        ForeignKeyConstraint(["plant_id", "sloc_id"],
                             ["storage_location.plant_id", "storage_location.sloc_id"]),
    )


class MaintenanceOrder(Base):   # AUFK/AFIH
    """정비오더. 설비 한 대에 대한 작업 지시로 요청·진행·완료를 거친다."""
    __tablename__ = "maintenance_order"
    order_no: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)  # AUFNR
    equipment_no: Mapped[str] = mapped_column(
        String(18), ForeignKey("equipment.equipment_no", ondelete="CASCADE"))
    order_type: Mapped[str] = mapped_column(String(2), default="PM")     # PM/CM
    status: Mapped[str] = mapped_column(String(6), default="REQ")
    priority: Mapped[str] = mapped_column(String(1), default="M")        # H/M/L
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(500))
    requester: Mapped[str | None] = mapped_column(String(40))
    request_date: Mapped[date] = mapped_column(Date)
    planned_date: Mapped[date | None] = mapped_column(Date)    # 예정일. 지연 판정 기준
    completed_date: Mapped[date | None] = mapped_column(Date)
    labor_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())

    equipment: Mapped["Equipment"] = relationship(back_populates="orders")
    parts: Mapped[list["MaintenanceOrderPart"]] = relationship(
        back_populates="order", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("order_type IN ('PM','CM')"),
        CheckConstraint("status IN ('REQ','WIP','DONE','CANCEL')"),
        CheckConstraint("priority IN ('H','M','L')"),
    )


class MaintenanceOrderPart(Base):   # RESB(예약) → MSEG(소비)
    """정비오더가 쓰는 부품.

    오더를 완료하면 이 항목들이 이동유형 261로 자재문서에 전기되고, 그때 생긴
    자재문서 번호를 posted_doc_no에 남겨 나중에 역추적할 수 있게 한다.
    전기 전에는 NULL인데, 예약만 되고 아직 재고에서 안 빠진 상태를 뜻한다.
    """
    __tablename__ = "maintenance_order_part"
    order_no: Mapped[int] = mapped_column(
        BigIntPK, ForeignKey("maintenance_order.order_no", ondelete="CASCADE"),
        primary_key=True)
    item_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    material_no: Mapped[str] = mapped_column(
        String(18), ForeignKey("material.material_no"))
    quantity: Mapped[float] = mapped_column(Numeric(15, 3))
    uom: Mapped[str] = mapped_column(String(3), default="EA")
    posted_doc_no: Mapped[int | None] = mapped_column(BigInteger)   # 전기된 자재문서

    order: Mapped["MaintenanceOrder"] = relationship(back_populates="parts")

    __table_args__ = (CheckConstraint("quantity > 0"),)
