"""수요예측 회귀모델 테스트."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analytics"))

from forecast.model import (
    fit_material_model, forecast_demand, model_summary,
)


def _synthetic(coef_temp: float, base: float = 30.0, n: int = 60) -> pd.DataFrame:
    """기온계수가 알려진 합성 데이터(노이즈 거의 없음)."""
    rows = []
    d0 = date(2026, 1, 1)
    for i in range(n):
        d = d0 + timedelta(days=i)
        temp = -5 + (i % 35)  # -5 ~ 29 반복
        wk = 1 if d.weekday() >= 5 else 0
        qty = max(0, base + coef_temp * temp + 3 * wk)
        rows.append({"date": pd.Timestamp(d), "avg_temp": float(temp),
                     "precip_mm": 0.0, "is_weekend": wk, "is_holiday": 0, "qty": float(qty)})
    return pd.DataFrame(rows)


def test_fit_and_coef_sign_heating():
    df = _synthetic(coef_temp=-1.5)
    s = model_summary(fit_material_model(df))
    assert s["temp_effect_per_1deg"] < -1.0   # 난방형
    assert s["r2"] > 0.95
    assert "난방형" in s["interpretation"]


def test_fit_and_coef_sign_cooling():
    df = _synthetic(coef_temp=+1.2)
    s = model_summary(fit_material_model(df))
    assert s["temp_effect_per_1deg"] > 1.0    # 냉방형
    assert "냉방형" in s["interpretation"]


def test_forecast_value():
    df = _synthetic(coef_temp=-1.5, base=30)
    m = fit_material_model(df)
    # base=30, coef=-1.5 → 기온 10℃, 평일: 약 30 -15 = 15
    pred = forecast_demand(m, avg_temp=10, is_weekend=0)
    assert 13 <= pred <= 17


def test_forecast_never_negative():
    df = _synthetic(coef_temp=-1.5, base=10)
    m = fit_material_model(df)
    assert forecast_demand(m, avg_temp=40) == 0.0   # 음수 보정


def test_insufficient_sample():
    df = _synthetic(coef_temp=-1.5, n=3)
    with pytest.raises(ValueError):
        fit_material_model(df)
