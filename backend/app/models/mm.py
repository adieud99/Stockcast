"""
SAP MM 구조 차용 ORM 모델.

SQL 스키마(db/migrations/01_schema.sql)와 1:1 대응한다.
컬럼 옆 주석의 대문자는 대응되는 SAP 표준 필드명이다.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger, CheckConstraint, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, Integer, Numeric, SmallInteger, String, func,
)

# PostgreSQL은 BIGINT(BIGSERIAL)로 자동증가, SQLite(테스트)는 INTEGER로 자동증가
BigIntPK = BigInteger().with_variant(Integer, "sqlite")
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Plant(Base):              # T001W
    __tablename__ = "plant"
    plant_id: Mapped[str] = mapped_column(String(4), primary_key=True)   # WERKS
    name: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StorageLocation(Base):    # T001L
    __tablename__ = "storage_location"
    plant_id: Mapped[str] = mapped_column(String(4), ForeignKey("plant.plant_id"), primary_key=True)
    sloc_id: Mapped[str] = mapped_column(String(4), primary_key=True)    # LGORT
    name: Mapped[str] = mapped_column(String(60))


class MaterialGroup(Base):      # T023
    __tablename__ = "material_group"
    group_code: Mapped[str] = mapped_column(String(9), primary_key=True)  # MATKL
    name: Mapped[str] = mapped_column(String(60))


class Material(Base):           # MARA + MAKT
    __tablename__ = "material"
    material_no: Mapped[str] = mapped_column(String(18), primary_key=True)   # MATNR
    description: Mapped[str] = mapped_column(String(120))                    # MAKTX
    material_type: Mapped[str] = mapped_column(String(4))                    # MTART
    group_code: Mapped[str | None] = mapped_column(String(9), ForeignKey("material_group.group_code"))
    base_uom: Mapped[str] = mapped_column(String(3), default="EA")           # MEINS
    unit_price: Mapped[float] = mapped_column(Numeric(12, 2), default=0)     # 판매단가(원)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Stock(Base):              # MARD
    __tablename__ = "stock"
    material_no: Mapped[str] = mapped_column(String(18), ForeignKey("material.material_no"), primary_key=True)
    plant_id: Mapped[str] = mapped_column(String(4), primary_key=True)
    sloc_id: Mapped[str] = mapped_column(String(4), primary_key=True)
    unrestricted_qty: Mapped[float] = mapped_column(Numeric(15, 3), default=0)  # LABST
    safety_stock: Mapped[float] = mapped_column(Numeric(15, 3), default=0)
    reorder_point: Mapped[float] = mapped_column(Numeric(15, 3), default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["plant_id", "sloc_id"],
                             ["storage_location.plant_id", "storage_location.sloc_id"]),
    )


class MovementType(Base):       # BWART 룩업
    __tablename__ = "movement_type"
    code: Mapped[str] = mapped_column(String(3), primary_key=True)       # BWART
    description: Mapped[str] = mapped_column(String(60))
    direction: Mapped[int] = mapped_column(SmallInteger)                 # +1 입고 / -1 출고
    __table_args__ = (CheckConstraint("direction IN (-1, 1)"),)


class MaterialDocHeader(Base):  # MKPF
    __tablename__ = "material_doc_header"
    doc_no: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)  # MBLNR
    posting_date: Mapped[date] = mapped_column(Date)                    # BUDAT
    doc_date: Mapped[date] = mapped_column(Date, server_default=func.current_date())  # BLDAT
    source: Mapped[str] = mapped_column(String(10), default="NFC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    items: Mapped[list["MaterialDocItem"]] = relationship(
        back_populates="header", cascade="all, delete-orphan")


class MaterialDocItem(Base):    # MSEG
    __tablename__ = "material_doc_item"
    doc_no: Mapped[int] = mapped_column(BigIntPK, ForeignKey("material_doc_header.doc_no", ondelete="CASCADE"), primary_key=True)
    item_no: Mapped[int] = mapped_column(Integer, primary_key=True)     # ZEILE
    material_no: Mapped[str] = mapped_column(String(18), ForeignKey("material.material_no"))
    plant_id: Mapped[str] = mapped_column(String(4))
    sloc_id: Mapped[str] = mapped_column(String(4))
    movement_type: Mapped[str] = mapped_column(String(3), ForeignKey("movement_type.code"))  # BWART
    quantity: Mapped[float] = mapped_column(Numeric(15, 3))             # MENGE
    uom: Mapped[str] = mapped_column(String(3), default="EA")
    header: Mapped["MaterialDocHeader"] = relationship(back_populates="items")
    __table_args__ = (
        CheckConstraint("quantity > 0"),
        ForeignKeyConstraint(["plant_id", "sloc_id"],
                             ["storage_location.plant_id", "storage_location.sloc_id"]),
    )


class NfcTag(Base):
    __tablename__ = "nfc_tag"
    tag_uid: Mapped[str] = mapped_column(String(64), primary_key=True)
    material_no: Mapped[str] = mapped_column(String(18), ForeignKey("material.material_no"))
    plant_id: Mapped[str] = mapped_column(String(4))
    sloc_id: Mapped[str] = mapped_column(String(4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["plant_id", "sloc_id"],
                             ["storage_location.plant_id", "storage_location.sloc_id"]),
    )


class StockSnapshotHistory(Base):   # 이력성 엔터티
    __tablename__ = "stock_snapshot_history"
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    material_no: Mapped[str] = mapped_column(String(18), ForeignKey("material.material_no"), primary_key=True)
    plant_id: Mapped[str] = mapped_column(String(4), primary_key=True)
    sloc_id: Mapped[str] = mapped_column(String(4), primary_key=True)
    unrestricted_qty: Mapped[float] = mapped_column(Numeric(15, 3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["plant_id", "sloc_id"],
                             ["storage_location.plant_id", "storage_location.sloc_id"]),
    )


class ExtWeather(Base):
    __tablename__ = "ext_weather"
    obs_date: Mapped[date] = mapped_column(Date, primary_key=True)
    region_code: Mapped[str] = mapped_column(String(10), default="108")
    avg_temp: Mapped[float | None] = mapped_column(Numeric(5, 2))
    min_temp: Mapped[float | None] = mapped_column(Numeric(5, 2))
    max_temp: Mapped[float | None] = mapped_column(Numeric(5, 2))
    precip_mm: Mapped[float | None] = mapped_column(Numeric(6, 2))


class ExtHoliday(Base):
    __tablename__ = "ext_holiday"
    holiday_date: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    is_holiday: Mapped[bool] = mapped_column(default=True)


class ExtRetailIndex(Base):     # 통계청 KOSIS 의류 소매판매액지수(월별 거시 수요)
    __tablename__ = "ext_retail_index"
    period: Mapped[str] = mapped_column(String(6), primary_key=True)      # 'YYYYMM'
    category: Mapped[str] = mapped_column(String(60), primary_key=True, default="의복")
    index_value: Mapped[float | None] = mapped_column(Numeric(8, 2))      # 지수값
    unit: Mapped[str | None] = mapped_column(String(20))


class ExtBidNotice(Base):       # 조달청 나라장터 입찰공고(물품) — 실제 조달 수요 신호
    __tablename__ = "ext_bid_notice"
    bid_no: Mapped[str] = mapped_column(String(40), primary_key=True)      # bidNtceNo
    bid_ord: Mapped[str] = mapped_column(String(10), primary_key=True, default="00")  # bidNtceOrd
    bid_name: Mapped[str | None] = mapped_column(String(300))              # bidNtceNm 공고명
    notice_agency: Mapped[str | None] = mapped_column(String(120))         # ntceInsttNm 공고기관
    demand_agency: Mapped[str | None] = mapped_column(String(120))         # dminsttNm 수요기관
    est_price: Mapped[float | None] = mapped_column(Numeric(18, 2))        # presmptPrc 추정가격
    notice_date: Mapped[date | None] = mapped_column(Date)                 # bidNtceDt 공고일
    category: Mapped[str | None] = mapped_column(String(40), default="물품")
