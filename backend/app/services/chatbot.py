"""운영 챗봇. 재고·예측·발주·설비를 자연어로 묻고 답한다.

ai_insight.py와 같은 방식으로 짰다.

질문이 들어오면 먼저 DB에서 실제 수치를 뽑아 컨텍스트를 만든다. LLM에게 DB를
직접 열어주지 않고 서버가 조회한 값만 넘기는데, 환각도 막고 권한도 통제되기
때문이다. 프롬프트에 없는 수치는 지어내지 말라고 명시한다.

LLM(Ollama/Gemini)이 있으면 그 컨텍스트로 서술형 답을 만들고, 없거나 실패하면
같은 컨텍스트를 규칙 기반으로 읽어서 답한다. 덕분에 키 없이도 오프라인에서도
챗봇이 돌아간다. 시연할 때 이게 중요했다.

컨텍스트를 질문에 따라 골라 담는 건 프롬프트 크기 때문이다. 전체를 매번 넣으면
로컬 Ollama가 확 느려져서, 의도를 먼저 뽑고 필요한 조각만 싣는다.
"""
from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.kpi import kpi_abc, kpi_monthly_issues, kpi_summary, kpi_turnover
from app.api.reorder import _analyze
from app.data.glossary import GLOSSARY
from app.models.mm import Material, Stock
from app.services.llm import get_provider
from app.services.maintenance import list_equipment, list_orders, maintenance_kpi

# 의도별 트리거 키워드. 위에서부터 검사하니 구체적인 의도를 앞에 둔다.
INTENTS: list[tuple[str, tuple[str, ...]]] = [
    ("glossary",    ("무슨 뜻", "뜻이", "뭐야", "뭔가요", "무엇인가", "설명해", "의미")),
    ("maintenance", ("설비", "정비", "고장", "가동률", "예방정비", "pm", "mttr", "유지보수")),
    ("reorder",     ("발주", "주문", "재주문", "보충", "얼마나 사", "언제 사")),
    ("shortage",    ("결품", "부족", "떨어", "품절", "위험")),
    ("abc",         ("abc", "매출", "파레토", "등급", "효자")),
    ("turnover",    ("회전율", "회전", "안 팔리", "재고가 도는")),
    ("forecast",    ("예측", "전망", "수요", "얼마나 팔", "내일", "다음 주", "날씨")),
    ("stock",       ("재고", "몇 개", "남았", "수량", "현재고")),
    ("kpi",         ("kpi", "요약", "현황", "상황", "지표", "전체")),
]

# 대시보드 옆 좁은 패널에서 읽을 거라 길이를 제한한다
_SYSTEM = (
    "당신은 StockCast 재고관리 백오피스의 운영 도우미입니다. "
    "아래 '데이터'에 있는 수치만 사용해 한국어로 답하세요. "
    "데이터에 없는 값은 절대 지어내지 말고 '해당 정보는 없습니다'라고 답하세요. "
    "3~5문장으로 간결하게, 숫자는 근거로 함께 제시하고, 마지막에 "
    "실무자가 취할 조치를 한 줄 덧붙이세요. 마크다운 표는 쓰지 마세요."
)


def detect_intent(message: str) -> str:
    m = message.lower()
    for name, keys in INTENTS:
        if any(k in m for k in keys):
            return name
    return "kpi"


def find_terms(message: str) -> list[str]:
    """질문에 나온 사전 용어를 찾는다. 툴팁이 쓰는 사전을 그대로 재사용."""
    return [t for t in GLOSSARY if t.lower() in message.lower()]


def find_materials(db: Session, message: str, limit: int = 5) -> list[Material]:
    """질문에 품목명이 들어 있는지 찾는다. '제설제 재고 얼마나 남았어' 같은 경우."""
    mats = db.scalars(select(Material)).all()
    hits = []
    for m in mats:
        # 품목명을 통째로 비교하면 거의 안 맞아서 토큰으로 쪼개 본다
        tokens = [t for t in re.split(r"[\s()·,]+", m.description) if len(t) >= 2]
        if m.material_no in message or any(t in message for t in tokens):
            hits.append(m)
    return hits[:limit]


# ── 컨텍스트 수집 ───────────────────────────────────────────────

def build_context(db: Session, message: str, intent: str) -> dict:
    """의도에 맞는 데이터만 담는다. KPI 요약은 어느 경우든 넣는다."""
    ctx: dict = {"질문의도": intent, "기준일": str(date.today())}
    ctx["핵심지표"] = kpi_summary(db)

    if intent == "glossary":
        terms = find_terms(message)
        ctx["용어설명"] = {t: {k: v for k, v in GLOSSARY[t].items()
                            if k in ("short", "detail", "formula")} for t in terms}
        if not terms:
            ctx["용어후보"] = list(GLOSSARY)[:40]

    if intent in ("reorder", "shortage", "stock"):
        recs = _analyze(db, lead_time=3, review=7, service_level=0.95, only_need=False)
        need = [r for r in recs if r["need_order"]]
        ctx["발주필요"] = [{"자재": r["description"], "현재고": r["current_qty"],
                        "권장발주": r["recommended_order_qty"],
                        "재주문점": r["reorder_point"],
                        "공급일수": r["days_of_supply"]} for r in need[:10]]
        ctx["공급일수_짧은순"] = [
            {"자재": r["description"], "현재고": r["current_qty"],
             "공급일수": r["days_of_supply"], "일평균수요": r["avg_daily_demand"]}
            for r in recs[:8]]

    if intent == "stock":
        hits = find_materials(db, message)
        if hits:
            rows = []
            for m in hits:
                st = db.scalars(select(Stock).where(
                    Stock.material_no == m.material_no)).all()
                rows.append({
                    "자재번호": m.material_no, "자재명": m.description,
                    "현재고": sum(float(s.unrestricted_qty) for s in st),
                    "안전재고": sum(float(s.safety_stock) for s in st),
                    "재주문점": sum(float(s.reorder_point) for s in st),
                    "단가": float(m.unit_price),
                })
            ctx["질문품목_재고"] = rows

    if intent in ("abc", "kpi"):
        ctx["ABC상위"] = [{"자재": r["description"], "매출액": r["sales_value"],
                         "누적비율": r["cum_ratio_pct"], "등급": r["grade"]}
                        for r in kpi_abc(db)[:8]]

    if intent in ("turnover", "kpi"):
        turn = [r for r in kpi_turnover(db) if r.get("turnover") is not None]
        ctx["회전율_빠른순"] = [{"자재": r["description"], "회전율": r["turnover"]}
                          for r in turn[:5]]
        ctx["회전율_느린순"] = [{"자재": r["description"], "회전율": r["turnover"]}
                          for r in sorted(turn, key=lambda r: r["turnover"])[:5]]

    if intent == "forecast":
        ctx["월별출고추이"] = kpi_monthly_issues(db, months=12)
        hits = find_materials(db, message, limit=3)
        if hits:
            ctx["질문품목"] = [{"자재번호": m.material_no, "자재명": m.description}
                           for m in hits]
        ctx["예측방법"] = ("다중회귀(기온·강수·주말·공휴일)와 "
                       "시계열(Holt-Winters)을 함께 사용. "
                       "상세 수치는 /api/forecast 에서 조회.")

    if intent == "maintenance":
        ctx["설비지표"] = maintenance_kpi(db)
        ctx["설비목록"] = [{"설비": e["name"], "상태": e["status"],
                        "다음정비일": str(e["next_pm_date"]) if e["next_pm_date"] else None,
                        "지연일수": e["overdue_days"]}
                       for e in list_equipment(db)[:8]]
        ctx["열린정비오더"] = [{"오더": o["order_no"], "설비": o["equipment_name"],
                          "유형": o["order_type"], "제목": o["title"],
                          "지연": o["is_overdue"]}
                         for o in list_orders(db, status_filter="REQ")[:5]
                         ] + [{"오더": o["order_no"], "설비": o["equipment_name"],
                               "유형": o["order_type"], "제목": o["title"],
                               "지연": o["is_overdue"]}
                              for o in list_orders(db, status_filter="WIP")[:5]]
    return ctx


# ── 규칙 기반 답변(LLM 없을 때) ─────────────────────────────────

def _won(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "-"


def rule_answer(ctx: dict, message: str, intent: str) -> str:
    k = ctx["핵심지표"]

    if intent == "glossary":
        terms = ctx.get("용어설명") or {}
        if terms:
            out = []
            for t, v in terms.items():
                line = f"[{t}] {v['short']} {v.get('detail', '')}"
                if v.get("formula"):
                    line += f" (계산식: {v['formula']})"
                out.append(line.strip())
            return " ".join(out)
        return ("사전에 등록된 용어를 찾지 못했습니다. "
                "예: 안전재고, 재주문점, 리드타임, 재고회전율, ABC분석, MTTR 등을 "
                "물어보시면 설명과 계산식을 드립니다.")

    if intent == "maintenance":
        m = ctx.get("설비지표", {})
        parts = [f"설비 {m.get('equipment_total')}대 중 {m.get('equipment_running')}대가 "
                 f"정상 가동 중이며 가동률은 {m.get('uptime_rate_pct')}%입니다."]
        if m.get("equipment_down"):
            parts.append(f"고장 정지 설비가 {m['equipment_down']}대 있습니다.")
        if m.get("pm_overdue_count"):
            parts.append(f"예방정비가 지연된 설비는 {m['pm_overdue_count']}대이고, "
                         f"7일 내 예정은 {m.get('pm_due_soon_count')}대입니다.")
        if m.get("mttr_days") is not None:
            parts.append(f"평균 수리시간(MTTR)은 {m['mttr_days']}일, "
                         f"기간 정비비용은 {_won(m.get('total_cost'))}원입니다.")
        parts.append("→ 지연된 예방정비부터 오더를 발행해 고장 전환을 막으세요.")
        return " ".join(parts)

    if intent in ("reorder", "shortage"):
        need = ctx.get("발주필요", [])
        if need:
            head = ", ".join(f"{r['자재']}(현재고 {_won(r['현재고'])} → 권장 "
                             f"{_won(r['권장발주'])}개)" for r in need[:3])
            return (f"지금 발주가 필요한 품목은 {len(need)}건입니다. 대표적으로 {head} "
                    f"입니다. 현재고가 재주문점 이하로 내려온 품목이며, "
                    f"권장 발주량은 발주상한에서 현재고를 뺀 값입니다. "
                    f"→ 공급일수가 짧은 품목부터 발주하세요.")
        low = ctx.get("공급일수_짧은순", [])
        tail = ""
        if low:
            r = low[0]
            tail = (f" 가장 여유가 적은 품목은 {r['자재']}로 공급일수 "
                    f"{r['공급일수']}일분입니다.")
        return ("현재 재주문점 이하로 내려온 품목은 없어 긴급 발주는 필요하지 않습니다."
                + tail + " → 계절 품목의 선제 발주 시점만 점검하세요.")

    if intent == "stock":
        rows = ctx.get("질문품목_재고", [])
        if rows:
            out = []
            for r in rows:
                out.append(f"{r['자재명']}({r['자재번호']})는 현재고 {_won(r['현재고'])}개, "
                           f"안전재고 {_won(r['안전재고'])}개, 재주문점 {_won(r['재주문점'])}개입니다.")
            return (" ".join(out) +
                    " → 현재고가 재주문점 이하이면 발주 대상입니다.")
        return (f"전체 {k['sku_count']}개 품목의 총 재고는 {_won(k['total_stock_qty'])}개, "
                f"재고자산금액은 {_won(k['inventory_value'])}원입니다. "
                f"특정 품목을 물으시면 품목명을 함께 적어 주세요(예: '제설제 재고').")

    if intent == "abc":
        rows = ctx.get("ABC상위", [])
        if rows:
            top = ", ".join(f"{r['자재']}({_won(r['매출액'])}원, {r['등급']}등급)"
                            for r in rows[:3])
            a_cnt = sum(1 for r in rows if r["등급"] == "A")
            return (f"매출 기여 상위 품목은 {top} 순입니다. 표시된 상위 목록 중 "
                    f"{a_cnt}개가 A등급(누적 매출 70% 이내)입니다. "
                    f"→ A등급은 서비스수준을 높이고 결품을 우선 방어하세요.")

    if intent == "turnover":
        fast = ctx.get("회전율_빠른순", [])
        slow = ctx.get("회전율_느린순", [])
        parts = [f"평균 재고회전율은 {k['avg_turnover']}회/년입니다."]
        if fast:
            parts.append(f"가장 빠른 품목은 {fast[0]['자재']}({fast[0]['회전율']}회/년)로 "
                         f"수요가 강해 결품 방어가 필요합니다.")
        if slow:
            parts.append(f"가장 느린 품목은 {slow[0]['자재']}({slow[0]['회전율']}회/년)로 "
                         f"과잉재고가 운전자본을 묶고 있습니다.")
        parts.append("→ 느린 품목의 발주량을 낮추고 빠른 품목의 안전재고를 올리세요.")
        return " ".join(parts)

    if intent == "forecast":
        monthly = ctx.get("월별출고추이", [])
        tail = ""
        if len(monthly) >= 2:
            last, prev = monthly[-1], monthly[-2]
            diff = last["issued"] - prev["issued"]
            direction = "증가" if diff > 0 else "감소"
            tail = (f" 최근 {last['month']} 출고는 {_won(last['issued'])}개로 "
                    f"전월 대비 {_won(abs(diff))}개 {direction}했습니다.")
        return ("수요예측은 기온·강수·주말·공휴일을 넣은 다중회귀와, 추세·요일 계절성을 "
                "잡는 시계열(Holt-Winters) 두 가지로 산출합니다." + tail +
                " → 품목별 상세 예측은 수요예측 API에서 품목번호로 조회하세요.")

    # 기본: KPI 요약
    return (f"현재 {k['sku_count']}개 품목, 재고자산 {_won(k['inventory_value'])}원을 "
            f"운영 중입니다. 평균 재고회전율 {k['avg_turnover']}회/년, 결품률 "
            f"{k['stockout_rate_pct']}%이며, 발주가 필요한 품목은 "
            f"{k['reorder_needed_count']}개, 안전재고 이하는 "
            f"{k['below_safety_count']}개입니다. "
            f"→ 재고·발주·설비·용어 무엇이든 물어보세요.")


# ── 진입점 ──────────────────────────────────────────────────────

def _build_prompt(ctx: dict, message: str, history: list[dict] | None) -> str:
    convo = ""
    if history:
        # 직전 3턴만 넣는다. 로컬 LLM은 프롬프트가 길어지면 급격히 느려진다
        recent = history[-6:]
        convo = "\n".join(f"{'사용자' if h.get('role') == 'user' else '도우미'}: "
                          f"{h.get('content', '')}" for h in recent)
        convo = f"\n\n이전 대화:\n{convo}"
    return (f"{_SYSTEM}{convo}\n\n"
            f"데이터:\n{json.dumps(ctx, ensure_ascii=False, indent=1, default=str)}\n\n"
            f"질문: {message}\n답변:")


def answer(db: Session, message: str, history: list[dict] | None = None,
           provider_name: str | None = None) -> dict:
    """질문 하나를 처리한다. LLM을 먼저 쓰고, 실패하면 규칙 기반으로 넘어간다."""
    message = (message or "").strip()
    if not message:
        return {"answer": "질문을 입력해 주세요.", "source": "rule",
                "intent": "empty", "terms": []}

    intent = detect_intent(message)
    ctx = build_context(db, message, intent)
    terms = find_terms(message)          # 답변 아래 용어 칩으로 노출

    provider = get_provider(provider_name)
    try:
        if provider.available():
            text = provider.generate(_build_prompt(ctx, message, history))
            if text:
                return {"answer": text, "source": provider.name,
                        "intent": intent, "terms": terms}
    except Exception:                     # noqa: BLE001
        pass                              # 키 없음, 네트워크, 타임아웃 전부 폴백

    return {"answer": rule_answer(ctx, message, intent), "source": "rule",
            "intent": intent, "terms": terms}


def suggestions(db: Session) -> list[str]:
    """첫 화면에 띄울 예시 질문. 지금 데이터 상태에 맞춰 바꿔 준다."""
    base = ["지금 발주해야 할 품목 알려줘",
            "재고회전율이 낮은 품목은?",
            "안전재고가 무슨 뜻이야?"]
    try:
        m = maintenance_kpi(db, days=365)
        if m.get("pm_overdue_count"):
            base.insert(0, "예방정비가 밀린 설비 있어?")
        else:
            base.append("설비 가동률 어때?")
    except Exception:                     # noqa: BLE001
        base.append("설비 가동률 어때?")
    return base[:4]
