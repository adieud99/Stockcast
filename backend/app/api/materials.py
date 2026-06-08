"""자재 마스터(Material) CRUD API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.mm import Material, MaterialGroup
from app.schemas.mm import (
    MaterialCreate, MaterialGroupOut, MaterialOut, MaterialUpdate,
)

router = APIRouter(prefix="/api/materials", tags=["자재 마스터"])


@router.get("", response_model=list[MaterialOut], summary="자재 목록 조회")
def list_materials(
    group_code: str | None = Query(None, description="자재그룹 필터"),
    q: str | None = Query(None, description="자재명 부분검색"),
    db: Session = Depends(get_db),
):
    stmt = select(Material)
    if group_code:
        stmt = stmt.where(Material.group_code == group_code)
    if q:
        stmt = stmt.where(Material.description.ilike(f"%{q}%"))
    return db.scalars(stmt.order_by(Material.material_no)).all()


@router.get("/{material_no}", response_model=MaterialOut, summary="자재 단건 조회")
def get_material(material_no: str, db: Session = Depends(get_db)):
    m = db.get(Material, material_no)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"자재 {material_no} 없음")
    return m


@router.post("", response_model=MaterialOut, status_code=status.HTTP_201_CREATED,
             summary="자재 등록")
def create_material(payload: MaterialCreate, db: Session = Depends(get_db)):
    if db.get(Material, payload.material_no):
        raise HTTPException(status.HTTP_409_CONFLICT, f"자재 {payload.material_no} 이미 존재")
    if payload.group_code and not db.get(MaterialGroup, payload.group_code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"자재그룹 {payload.group_code} 없음")
    m = Material(**payload.model_dump())
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.patch("/{material_no}", response_model=MaterialOut, summary="자재 수정")
def update_material(material_no: str, payload: MaterialUpdate, db: Session = Depends(get_db)):
    m = db.get(Material, material_no)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"자재 {material_no} 없음")
    data = payload.model_dump(exclude_unset=True)
    if data.get("group_code") and not db.get(MaterialGroup, data["group_code"]):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"자재그룹 {data['group_code']} 없음")
    for k, v in data.items():
        setattr(m, k, v)
    db.commit()
    db.refresh(m)
    return m


@router.delete("/{material_no}", status_code=status.HTTP_204_NO_CONTENT, summary="자재 삭제")
def delete_material(material_no: str, db: Session = Depends(get_db)):
    m = db.get(Material, material_no)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"자재 {material_no} 없음")
    db.delete(m)
    db.commit()


@router.get("/groups/all", response_model=list[MaterialGroupOut], tags=["마스터"],
            summary="자재그룹 목록")
def list_groups(db: Session = Depends(get_db)):
    return db.scalars(select(MaterialGroup).order_by(MaterialGroup.group_code)).all()
