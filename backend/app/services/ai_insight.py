"""AI 자연어 해석 — 예측·재고·발주 결과를 한국어로 요약.

설계:
  - 설정된 LLM provider(Gemini 무료등급/Ollama)가 가능하면 LLM 요약.
  - 불가능하거나 실패하면 규칙 기반(rule-based) 요약으로 폴백.
    → 키 없이도 항상 동작(비용 0, 결정적 결과).
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.api.kpi import kpi_abc, kpi_summary, kpi_turnover
from app.api.reorder import _analyze
from app.services.llm import get_provider


def gather_context(db: Session) -> dict:
    """LLM/규칙 요약에 쓸 구조화 컨텍스트(경영·수요·재고건전성·ABC)."""
    kpi = kpi_summary(db)
    abc = kpi_abc(db)
    turn = kpi_turnover(db)
    recs = _analyze(db, lead_time=3, review=7, service_level=0.95, only_need=False)

    need = [r for r in recs if r["need_order"]]
    low = sorted(
        recs, key=lambda r: (r["days_of_supply"] is None, r["days_of_supply"] or 1e9)
    )[:3]
    a_items = [r for r in abc if r["grade"] == "A"]
    tv = [r for r in turn if r.get("turnover") is not None]
    fast = tv[:3]
    slow = sorted(tv, key=lambda r: r["turnover"])[:3]

    return {
        "kpi": kpi,
        "abc": {
            "A등급_품목수": len(a_items),
            "A등급_대표": [r["description"] for r in a_items[:3]],
            "전체_품목수": len(abc),
        },
        "회전_빠른_품목": [{"자재": r["description"], "회전율": r["turnover"]} for r in fast],
        "회전_느린_품목": [{"자재": r["description"], "회전율": r["turnover"]} for r in slow],
        "need_order": [
            {"자재": r["description"], "현재고": r["current_qty"],
             "권장발주": r["recommended_order_qty"], "공급일수": r["days_of_supply"]}
            for r in need
        ],
        "재고부족_상위": [
            {"자재": r["description"], "공급일수": r["days_of_supply"],
             "현재고": r["current_qty"]}
            for r in low
        ],
    }


def build_alerts(ctx: dict) -> list[str]:
    alerts = []
    for r in ctx["need_order"]:
        alerts.append(
            f"[발주 권장] {r['자재']} — 현재고 {r['현재고']}개, "
            f"권장 발주 {r['권장발주']}개 (공급 {r['공급일수']}일분)")
    for r in ctx["재고부족_상위"]:
        if r["공급일수"] is not None and r["공급일수"] < 7:
            alerts.append(f"[결품 경고] {r['자재']} — 공급일수 {r['공급일수']}일로 임박")
    return alerts


def rule_based_summary(ctx: dict) -> dict:
    """규칙 기반 한국어 요약(LLM 없이) — 경영·수요·재고건전성·ABC 근거 포함."""
    k = ctx["kpi"]
    inv = k.get("inventory_value", 0)
    parts = []

    # 1) 운영 현황
    parts.append(
        f"[운영 현황] 전체 {k['sku_count']}개 품목, 재고자산 약 {int(inv):,}원을 운영 "
        f"중입니다. 평균 재고회전율은 {k['avg_turnover']}회/년, 결품률은 "
        f"{k['stockout_rate_pct']}%입니다.")

    # 2) 수요·회전 분석
    fast, slow = ctx.get("회전_빠른_품목", []), ctx.get("회전_느린_품목", [])
    if fast:
        f = fast[0]
        parts.append(
            f"[수요 분석] 회전이 가장 빠른 '{f['자재']}'(회전율 {f['회전율']}회/년)는 "
            f"수요가 강해 결품 방지를 위한 충분한 안전재고가 필요합니다.")
    if slow:
        s = slow[0]
        parts.append(
            f"반면 회전이 느린 '{s['자재']}'(회전율 {s['회전율']}회/년)는 과잉재고로 "
            f"운전자본이 묶일 수 있어 발주량 하향을 검토해야 합니다.")

    # 3) 재고 건전성
    if k["reorder_needed_count"] > 0:
        parts.append(
            f"[재고 건전성] 재주문점 이하로 발주가 필요한 품목이 "
            f"{k['reorder_needed_count']}개, 안전재고 이하(결품 위험)가 "
            f"{k['below_safety_count']}개입니다.")
    else:
        parts.append("[재고 건전성] 전 품목이 재주문점 이상으로 현재 재고는 안정적입니다.")

    # 4) 경영(ABC) 관점
    abc = ctx.get("abc", {})
    if abc.get("A등급_품목수"):
        rep = ", ".join(abc.get("A등급_대표", []))
        parts.append(
            f"[경영 관점] 매출 상위 A등급 {abc['A등급_품목수']}개 품목이 전체 매출의 "
            f"약 70%를 차지합니다({rep} 등). 이들에 재고·발주 관리를 집중하는 것이 "
            f"운전자본 효율을 높입니다.")

    # 5) 권장 조치
    if ctx["need_order"]:
        names = ", ".join(r["자재"] for r in ctx["need_order"][:3])
        parts.append(
            f"[권장 조치] {names} 등 발주 필요 품목을 우선 보충하고, 공급일수가 짧은 "
            f"품목의 결품을 점검하세요.")
    else:
        parts.append(
            "[권장 조치] 긴급 발주는 없으나, 계절 수요 품목(제설·냉난방 등)의 "
            "선제 발주 시점을 점검하세요.")

    return {"summary": " ".join(parts), "alerts": build_alerts(ctx), "source": "rule"}


def _build_prompt(ctx: dict) -> str:
    return (
        "당신은 재고관리 백오피스 분석가입니다. 아래 JSON 데이터를 바탕으로 "
        "경영진이 읽을 한국어 운영 요약을 작성하세요. 다음 5개 관점을 각 1~2문장씩, "
        "근거(데이터)→해석→권장조치 흐름으로 서술하세요: "
        "①운영 현황(품목수·재고자산·회전율·결품률) "
        "②수요·회전 분석(빠른/느린 품목과 그 의미) "
        "③재고 건전성(발주 필요·안전재고 이하) "
        "④경영 관점(ABC 상위 품목 집중관리) "
        "⑤권장 조치. "
        "각 관점 앞에 [운영 현황] 같은 머리표를 붙이고, 데이터에 없는 수치는 "
        "지어내지 마세요.\n\n"
        f"데이터:\n{json.dumps(ctx, ensure_ascii=False, indent=2)}"
    )


def generate_insight(db: Session, provider_name: str | None = None) -> dict:
    """AI 해석 생성. LLM 우선, 실패 시 규칙 기반 폴백."""
    ctx = gather_context(db)
    provider = get_provider(provider_name)
    try:
        if provider.available():
            text = provider.generate(_build_prompt(ctx))
            if text:
                return {"summary": text, "alerts": build_alerts(ctx),
                        "source": provider.name}
    except Exception:
        pass  # 키 없음/네트워크/응답오류 → 폴백
    return rule_based_summary(ctx)
