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
from forecast.timeseries import (  # noqa: E402
    build_daily_series, forecast_holt_winters, forecast_sarima,
)

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
        # from e 를 붙여야 원래 예외가 트레이스백에 남는다.
        # 안 붙이면 "왜 400인지"가 로그에서 끊긴다.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    summary = model_summary(m)
    summary["material_no"] = material_no
    summary["predicted_qty"] = forecast_demand(
        m, avg_temp=avg_temp, precip_mm=precip_mm,
        is_weekend=is_weekend, is_holiday=is_holiday)
    summary["input"] = {"avg_temp": avg_temp, "precip_mm": precip_mm,
                        "is_weekend": is_weekend, "is_holiday": is_holiday}
    return summary


@router.get("/{material_no}/timeseries", summary="시계열 수요예측 (Holt-Winters / SARIMA)")
def forecast_timeseries(
    material_no: str,
    horizon: int = Query(14, ge=1, le=60, description="예측 일수"),
    method: str = Query("holt-winters", pattern="^(holt-winters|sarima)$",
                        description="holt-winters(기본, 30일 이상) | sarima(60일 이상)"),
    db: Session = Depends(get_db),
):
    """과거 수요의 추세와 요일 계절성으로 앞으로 N일을 예측한다. 외부변수는 필요 없다.

    두 모델을 같은 응답 형식으로 내보내 비교할 수 있게 했다. Holt-Winters는
    표본이 적어도 돌고 MAPE를 같이 주며, SARIMA는 표본이 충분할 때(60일 이상)
    차분과 자기상관까지 본다."""
    if not db.get(Material, material_no):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"자재 {material_no} 없음")
    df = build_features(db)
    g = df[df.material_no == material_no]
    series = build_daily_series(g)
    fn = forecast_sarima if method == "sarima" else forecast_holt_winters
    try:
        result = fn(series, horizon)
    except ValueError as e:
        # from e 를 붙여야 원래 예외가 트레이스백에 남는다.
        # 안 붙이면 "왜 400인지"가 로그에서 끊긴다.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    result["material_no"] = material_no
    return result
