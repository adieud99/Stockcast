"""안전재고·ROP·발주 권고 로직 테스트."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "analytics"))

from inventory.reorder import (
    reorder_point, recommend, safety_stock, z_value,
)


def test_z_value():
    assert z_value(0.95) == 1.6449
    assert z_value(0.99) == 2.3263
    # 표에 없는 값 → 가장 가까운 값
    assert z_value(0.951) == 1.6449


def test_safety_stock_increases_with_variability():
    low = safety_stock(daily_std=2, lead_time_days=4, service_level=0.95)
    high = safety_stock(daily_std=10, lead_time_days=4, service_level=0.95)
    assert high > low > 0


def test_safety_stock_increases_with_service_level():
    s95 = safety_stock(5, 4, 0.95)
    s99 = safety_stock(5, 4, 0.99)
    assert s99 > s95


def test_reorder_point_formula():
    ss = safety_stock(5, 4, 0.95)            # = 1.6449*5*2 = 16.449
    rop = reorder_point(avg_daily_demand=10, lead_time_days=4, ss=ss)
    assert abs(rop - (10 * 4 + ss)) < 1e-6   # 40 + SS


def test_recommend_triggers_order_when_low():
    # 현재고 10, 일수요 10 → 재주문점보다 낮음 → 발주 필요
    r = recommend(current_qty=10, avg_daily_demand=10, daily_std=3,
                  lead_time_days=3, review_days=7)
    assert r["need_order"] is True
    assert r["recommended_order_qty"] > 0
    # 발주상한 ≈ 10*(3+7)+SS = 100+SS, 발주량 ≈ 그 - 10
    assert r["recommended_order_qty"] >= 90


def test_recommend_no_order_when_sufficient():
    r = recommend(current_qty=500, avg_daily_demand=10, daily_std=3,
                  lead_time_days=3, review_days=7)
    assert r["need_order"] is False
    assert r["recommended_order_qty"] == 0
    assert r["days_of_supply"] == 50.0       # 500/10


def test_recommend_zero_demand():
    r = recommend(current_qty=100, avg_daily_demand=0, daily_std=0)
    assert r["need_order"] is False
    assert r["days_of_supply"] is None       # 0 나눗셈 방어
