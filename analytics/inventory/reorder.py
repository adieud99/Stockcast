"""재고·발주 실무 로직 — 안전재고(Safety Stock)·재주문점(ROP)·권장 발주량.

경영/SCM 표준 공식 사용:
  안전재고  SS  = Z × σ_d × √L
  재주문점  ROP = d̄ × L + SS
  발주상한  S   = d̄ × (L + R) + SS         (order-up-to level)
  권장발주량    = max(0, ⌈S − 현재고⌉)       (현재고 ≤ ROP 일 때)

  Z: 서비스수준(결품 허용도)에 대응하는 표준정규 분위수
  d̄: 일평균 수요, σ_d: 일수요 표준편차
  L: 리드타임(일), R: 발주주기(검토주기, 일)

→ "결품을 X% 이내로 막으려면 지금 며칠분/몇 개를 발주해야 하는가"를 산출한다.
"""
from __future__ import annotations

import math

import pandas as pd

# 서비스수준 → Z (결품 허용 1−SL)
SERVICE_Z = {0.80: 0.8416, 0.90: 1.2816, 0.95: 1.6449,
             0.975: 1.9600, 0.98: 2.0537, 0.99: 2.3263}


def z_value(service_level: float) -> float:
    if service_level in SERVICE_Z:
        return SERVICE_Z[service_level]
    # 표에 없으면 가장 가까운 값 사용
    nearest = min(SERVICE_Z, key=lambda s: abs(s - service_level))
    return SERVICE_Z[nearest]


def safety_stock(daily_std: float, lead_time_days: float,
                 service_level: float = 0.95) -> float:
    return z_value(service_level) * daily_std * math.sqrt(max(lead_time_days, 0))


def reorder_point(avg_daily_demand: float, lead_time_days: float,
                  ss: float) -> float:
    return avg_daily_demand * lead_time_days + ss


def demand_stats(df_mat: pd.DataFrame, window_days: int = 90) -> dict:
    """자재별 일수요 평균·표준편차(최근 window_days)."""
    d = df_mat.sort_values("date").tail(window_days)
    qty = d["qty"].astype(float)
    return {
        "avg_daily_demand": round(float(qty.mean()), 3) if len(qty) else 0.0,
        "daily_std": round(float(qty.std(ddof=1)), 3) if len(qty) > 1 else 0.0,
        "n": int(len(qty)),
    }


def recommend(current_qty: float, avg_daily_demand: float, daily_std: float,
              lead_time_days: float = 3, review_days: float = 7,
              service_level: float = 0.95) -> dict:
    """단일 자재 발주 권고 산출."""
    ss = safety_stock(daily_std, lead_time_days, service_level)
    rop = reorder_point(avg_daily_demand, lead_time_days, ss)
    order_up_to = avg_daily_demand * (lead_time_days + review_days) + ss
    need_order = current_qty <= rop
    order_qty = math.ceil(max(0.0, order_up_to - current_qty)) if need_order else 0
    days_of_supply = (current_qty / avg_daily_demand) if avg_daily_demand > 0 else float("inf")
    return {
        "current_qty": round(float(current_qty), 1),
        "avg_daily_demand": round(avg_daily_demand, 2),
        "safety_stock": round(ss, 1),
        "reorder_point": round(rop, 1),
        "order_up_to": round(order_up_to, 1),
        "need_order": need_order,
        "recommended_order_qty": int(order_qty),
        "days_of_supply": (round(days_of_supply, 1)
                           if math.isfinite(days_of_supply) else None),
        "service_level": service_level,
        "lead_time_days": lead_time_days,
    }
