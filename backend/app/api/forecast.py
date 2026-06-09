"""수요예측 API — 품목별 회귀모델 요약 및 예측."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.mm import Material

# analytics 패키지 경로 등록
ANALYTICS = Path(__file__).resolve().parents[3] / "analytics"
if str(ANALYTICS) not in sys.path:
    sys.path.insert(0, str(ANALYTICS))

from forecast.data_prep import build_features  # noqa: E402
from forecast.model import fit_material_model, forecast_demand, model_summary  # noqa: E402

router = APIRouter(prefix="/api/forecast", tags=["수요예측"])


@router.get("", summary="전 품목 회귀모델 요약")
def forecast_all(db: Session = Depends(get_db)):
    df = build_features(db)
    if df.empty:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "분석할 출고 데이터가 없습니다")
    result = []
    for mat, g in df.groupby("material_no"):
        try:
            m = fit_material_model(g)
            s = model_summary(m)
            s["material_no"] = mat
            result.append(s)
        except ValueError:
            continue
    return result


@router.get("/{material_no}", summary="특정 품목 수요 예측")
def forecast_one(
    material_no: str,
    avg_temp: float = Query(..., description="예측 시점 평균기온(℃)"),
    precip_mm: float = Query(0, description="예측 시점 강수량(mm)"),
    is_weekend: int = Query(0, ge=0, le=1),
    is_holiday: int = Query(0, ge=0, le=1),
    db: Session = Depends(get_db),
):
    if not db.get(Material, material_no):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"자재 {material_no} 없음")
    df = build_features(db)
    g = df[df.material_no == material_no]
    if g.empty:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "해당 품목 출고 데이터 없음")
    try:
        m = fit_material_model(g)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    summary = model_summary(m)
    summary["material_no"] = material_no
    summary["predicted_qty"] = forecast_demand(
        m, avg_temp=avg_temp, precip_mm=precip_mm,
        is_weekend=is_weekend, is_holiday=is_holiday)
    summary["input"] = {"avg_temp": avg_temp, "precip_mm": precip_mm,
                        "is_weekend": is_weekend, "is_holiday": is_holiday}
    return summary
