"""시계열 수요예측 — Holt-Winters(지수평활) + SARIMA.

회귀(외부변수 기반)와 달리, 과거 수요의 '추세·계절성'만으로 미래를 예측한다.
  - 회귀(model.py): "기온·강수가 수요에 주는 영향" 설명 + 조건부 예측
  - 시계열(이 파일): 외부변수 없이도 다음 N일 수요를 추세·요일성으로 예측
"""
from __future__ import annotations

import warnings

import pandas as pd
from statsmodels.tsa.holtwinters import ExponentialSmoothing

warnings.filterwarnings("ignore")


def build_daily_series(df_mat: pd.DataFrame) -> pd.Series:
    """일별 출고 시계열(결측일 0 보간)."""
    s = (df_mat.set_index("date")["qty"].astype(float)
         .groupby(level=0).sum().sort_index())
    if s.empty:
        return s
    full = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(full, fill_value=0)


def forecast_holt_winters(series: pd.Series, horizon: int = 14) -> dict:
    """Holt-Winters로 향후 horizon일 예측 + 정확도(MAPE)."""
    if len(series) < 30:
        raise ValueError("시계열 표본이 부족합니다(최소 30일).")

    train, test = series[:-horizon], series[-horizon:]
    fit_eval = ExponentialSmoothing(
        train, trend="add", seasonal="add", seasonal_periods=7,
        initialization_method="estimated").fit()
    pred_eval = fit_eval.forecast(horizon).clip(lower=0)
    denom = test.replace(0, pd.NA)
    mape = float((abs(test - pred_eval) / denom).dropna().mean() * 100) \
        if denom.notna().any() else None

    fit = ExponentialSmoothing(
        series, trend="add", seasonal="add", seasonal_periods=7,
        initialization_method="estimated").fit()
    fc = fit.forecast(horizon).clip(lower=0)
    return {
        "method": "Holt-Winters (지수평활, 주간 계절성)",
        "horizon": horizon,
        "mape": round(mape, 1) if mape is not None else None,
        "forecast": [{"date": d.date().isoformat(), "qty": round(float(v), 1)}
                     for d, v in fc.items()],
        "next7_total": round(float(fc[:7].sum()), 0),
    }


def forecast_sarima(series: pd.Series, horizon: int = 14) -> dict:
    """SARIMA 예측(옵션). 실패 시 예외."""
    from statsmodels.tsa.statespace.sarimax import SARIMAX
    if len(series) < 60:
        raise ValueError("SARIMA 표본 부족(최소 60일).")
    fit = SARIMAX(series, order=(1, 1, 1), seasonal_order=(1, 0, 1, 7),
                  enforce_stationarity=False, enforce_invertibility=False).fit(disp=False)
    fc = fit.forecast(horizon).clip(lower=0)
    return {
        "method": "SARIMA(1,1,1)(1,0,1)7",
        "horizon": horizon,
        "forecast": [{"date": d.date().isoformat(), "qty": round(float(v), 1)}
                     for d, v in fc.items()],
        "next7_total": round(float(fc[:7].sum()), 0),
    }
