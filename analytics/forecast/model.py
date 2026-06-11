"""수요예측 — 품목별 다중선형회귀(OLS).

독립변수: 평균기온, 주말여부, 공휴일여부
종속변수: 일별 출고량(qty)

OLS를 쓰는 이유: 계수·R²·p-value를 그대로 해석할 수 있어
"기온 1℃ 상승 → 출고 X개 변화" 같은 백오피스 의사결정 근거를 만들 수 있다.
"""
from __future__ import annotations

import math

import pandas as pd
import statsmodels.api as sm

FEATURES = ["avg_temp", "precip_mm", "is_weekend", "is_holiday"]


def _safe(v, ndigits: int = 4):
    """NaN/Inf는 JSON 호환이 안 되므로 None으로 치환(분산 0 변수 등에서 발생)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, ndigits) if math.isfinite(f) else None


def fit_material_model(df_mat: pd.DataFrame):
    """단일 자재 출고 데이터로 OLS 적합. 반환: statsmodels 결과 객체."""
    d = df_mat.dropna(subset=["avg_temp"]).copy()
    d["precip_mm"] = d["precip_mm"].fillna(0)
    if len(d) < len(FEATURES) + 2:
        raise ValueError("표본이 부족합니다(회귀 불가).")
    X = sm.add_constant(d[FEATURES], has_constant="add")
    y = d["qty"].astype(float)
    return sm.OLS(y, X).fit()


def model_summary(model) -> dict:
    """모델 핵심 지표 요약(직렬화 가능 dict)."""
    coef = {k: _safe(v) for k, v in model.params.items()}
    pval = {k: _safe(v) for k, v in model.pvalues.items()}
    temp_coef = coef.get("avg_temp") or 0.0
    direction = ("기온↑ → 출고↑ (냉방형)" if temp_coef > 0.05
                 else "기온↑ → 출고↓ (난방형)" if temp_coef < -0.05
                 else "기온 영향 미미")
    r2 = _safe(model.rsquared, 3) or 0.0
    return {
        "r2": r2,
        "r2_adj": _safe(model.rsquared_adj, 3),
        "n": int(model.nobs),
        "coef": coef,
        "pvalue": pval,
        "temp_effect_per_1deg": round(temp_coef, 3),
        "interpretation": (
            f"기온 1℃ 상승 시 일 출고 {temp_coef:+.2f}개 변화 — {direction}. "
            f"설명력 R²={r2:.2f}."
        ),
    }


def forecast_demand(model, avg_temp: float, precip_mm: float = 0,
                    is_weekend: int = 0, is_holiday: int = 0) -> float:
    """주어진 조건의 일 수요 예측값(음수는 0으로 보정)."""
    X = pd.DataFrame([{"const": 1.0, "avg_temp": avg_temp, "precip_mm": precip_mm,
                       "is_weekend": is_weekend, "is_holiday": is_holiday}])
    pred = float(model.predict(X)[0])
    if not math.isfinite(pred):
        return 0.0
    return max(0.0, round(pred, 2))


def forecast_horizon(model, weather: list[dict]) -> list[dict]:
    """향후 기간 일별 예측. weather: [{date, avg_temp, is_weekend, is_holiday}]"""
    out = []
    for w in weather:
        out.append({
            "date": w["date"],
            "predicted_qty": forecast_demand(
                model, w["avg_temp"], w.get("is_weekend", 0), w.get("is_holiday", 0)),
        })
    return out
