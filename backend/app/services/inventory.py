"""재고 전기(posting) 서비스 — SAP MM 'Goods Movement' 핵심 로직.

설계: 입출고는 자재문서(MKPF 헤더 + MSEG 항목)로 기록되고,
      재고(stock)는 이동유형 방향(+1/-1) × 수량 만큼 갱신된다.
      → 이동이 진실의 원천, 재고는 그 결과(실무 SAP와 동일).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.mm import (
    Material, MaterialDocHeader, MaterialDocItem, MovementType, NfcTag, Stock,
)
from app.schemas.movement import (
    GoodsMovementCreate, GoodsMovementLine, MovementResult, MovementResultLine,
    NfcScanRequest,
)


def _apply_line(db: Session, line: GoodsMovementLine) -> tuple[MaterialDocItem, Decimal]:
    """항목 1건 검증 + 재고 갱신. (커밋은 호출자가 수행)"""
    if not db.get(Material, line.material_no):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"자재 {line.material_no} 없음")

    mvt = db.get(MovementType, line.movement_type)
    if not mvt:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"이동유형 {line.movement_type} 없음")

    stock = db.get(Stock, (line.material_no, line.plant_id, line.sloc_id))
    if not stock:
        # 재고 레코드가 없으면 0에서 시작(입고 시 신규 생성)
        if mvt.direction < 0:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"{line.material_no} 재고 레코드 없음(출고 불가)")
        stock = Stock(material_no=line.material_no, plant_id=line.plant_id,
                      sloc_id=line.sloc_id, unrestricted_qty=Decimal(0))
        db.add(stock)
        db.flush()

    delta = Decimal(line.quantity) * mvt.direction
    new_qty = Decimal(stock.unrestricted_qty) + delta
    if new_qty < 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{line.material_no} 재고 부족: 현재 {stock.unrestricted_qty}, 출고 {line.quantity}",
        )
    stock.unrestricted_qty = new_qty

    item = MaterialDocItem(
        item_no=0,  # 호출자가 재부여
        material_no=line.material_no, plant_id=line.plant_id, sloc_id=line.sloc_id,
        movement_type=line.movement_type, quantity=line.quantity, uom=line.uom,
    )
    return item, new_qty


def post_goods_movement(db: Session, payload: GoodsMovementCreate) -> MovementResult:
    """자재문서 전기: 헤더 1건 + 항목 N건 생성, 재고 갱신."""
    header = MaterialDocHeader(
        posting_date=payload.posting_date or date.today(),
        source=payload.source,
    )
    db.add(header)
    db.flush()

    result_lines: list[MovementResultLine] = []
    for idx, line in enumerate(payload.lines, start=1):
        item, new_qty = _apply_line(db, line)
        item.doc_no = header.doc_no
        item.item_no = idx
        db.add(item)
        result_lines.append(MovementResultLine(
            material_no=line.material_no, movement_type=line.movement_type,
            quantity=line.quantity, new_qty=new_qty,
        ))

    db.commit()
    db.refresh(header)
    return MovementResult(
        doc_no=header.doc_no, posting_date=header.posting_date,
        source=header.source, created_at=header.created_at, lines=result_lines,
    )


def post_nfc_scan(db: Session, scan: NfcScanRequest) -> MovementResult:
    """NFC 스캔 1건 → 태그 해석 → 자재문서 전기."""
    tag = db.get(NfcTag, scan.tag_uid)
    if not tag:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"등록되지 않은 NFC 태그: {scan.tag_uid}")
    payload = GoodsMovementCreate(
        source=scan.source,
        lines=[GoodsMovementLine(
            material_no=tag.material_no, plant_id=tag.plant_id, sloc_id=tag.sloc_id,
            movement_type=scan.movement_type, quantity=scan.quantity,
        )],
    )
    return post_goods_movement(db, payload)
