"""AI 자연어 해석 — 예측·재고·발주 결과를 한국어로 요약.

설계:
  - 설정된 LLM provider(Gemini 무료등급/Ollama)가 가능하면 LLM 요약.
  - 불가능하거나 실패하면 규칙 기반(rule-based) 요약으로 폴백.
    → 키 없이도 항상 동작(비용 0, 결정적 결과).
"""
from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.api.kpi import kpi_summary
from app.api.reorder import _analyze
from app.services.llm import get_provider


def gather_context(db: Session) -> dict:
    """LLM/규칙 요약에 쓸 구조화 컨텍스트."""
    kpi = kpi_summary(db)
    recs = _analyze(db, lead_time=3, review=7, service_level=0.95, only_need=False)
    need = [r for r in recs if r["need_order"]]
    low = sorted(
        recs, key=lambda r: (r["days_of_supply"] is None, r["days_of_supply"] or 1e9)
    )[:3]
    return {
        "kpi": kpi,
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
    """규칙 기반 한국어 요약(LLM 없이)."""
    k = ctx["kpi"]
    parts = [
        f"전체 {k['sku_count']}개 품목을 운영 중이며, 평균 재고회전율은 "
        f"{k['avg_turnover']}회/년, 결품률은 {k['stockout_rate_pct']}%입니다.",
    ]
    if k["reorder_needed_count"] > 0:
        parts.append(f"현재 발주가 필요한 품목은 {k['reorder_needed_count']}개입니다.")
    else:
        parts.append("현재 재고는 전 품목 재주문점 이상으로 안정적입니다.")
    if k["below_safety_count"] > 0:
        parts.append(f"안전재고 이하로 떨어진 품목이 {k['below_safety_count']}개 있어 "
                     "결품 위험을 점검해야 합니다.")
    return {"summary": " ".join(parts), "alerts": build_alerts(ctx), "source": "rule"}


def _build_prompt(ctx: dict) -> str:
    return (
        "당신은 재고관리 백오피스 분석가입니다. 아래 JSON 데이터를 바탕으로 "
        "경영진이 읽을 한국어 요약을 3~4문장으로 작성하세요. "
        "발주가 필요한 품목과 결품 위험을 구체적으로 언급하고 권장 조치를 제시하되, "
        "데이터에 없는 수치는 지어내지 마세요.\n\n"
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
