"""운영 화면이 쓰는 서비스. 헬스체크, 서버 리소스, 데이터 정합성 점검.

운영자가 SSH 없이 브라우저에서 시스템 상태를 볼 수 있게 만들었다.
구성요소 생사(DB·Odoo·LLM), 서버 리소스, 데이터 정합성을 한군데서 모은다.
헬스체크 결과는 자동 복구 스크립트도 그대로 폴링한다.

정합성 점검은 (코드, 이름, 심각도, 통과여부, 건수, 설명, 조치)를 돌려준다.
몇 건 틀렸다고만 하면 운영자가 할 수 있는 게 없어서 조치까지 같이 준다.
"""
from __future__ import annotations

import os
import platform
import shutil
import sys
import time
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.core.logbuffer import STARTED_AT, stats as log_stats
from app.models.maintenance import Equipment, MaintenanceOrder, MaintenanceOrderPart
from app.models.mm import (
    ExtBidNotice, ExtHoliday, ExtShopPrice, ExtWeather, Material,
    MaterialDocHeader, MaterialDocItem, MovementType, NfcTag, Stock,
    StockSnapshotHistory,
)
from app.services.llm import get_provider

# 심각도 — 화면 배지 색과 정렬 기준
SEV_CRITICAL = "critical"
SEV_WARNING = "warning"
SEV_INFO = "info"


# ── 1) 헬스체크 ─────────────────────────────────────────────────

def _check_db() -> dict:
    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "dialect": engine.dialect.name, "error": None}
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "latency_ms": None,
                "dialect": engine.dialect.name, "error": str(e)}


def _check_odoo() -> dict:
    """Odoo XML-RPC 인증까지 해본다. 키를 안 넣은 경우는 장애와 구분한다."""
    if not (settings.odoo_password or settings.odoo_api_key):
        return {"ok": False, "configured": False, "latency_ms": None,
                "error": "ODOO_PASSWORD/ODOO_API_KEY 미설정"}
    started = time.perf_counter()
    try:
        from app.services.odoo import _connect
        _connect()
        return {"ok": True, "configured": True,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "url": settings.odoo_url, "db": settings.odoo_db, "error": None}
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "configured": True, "latency_ms": None,
                "url": settings.odoo_url, "error": str(e)}


def _check_llm() -> dict:
    """LLM이 죽어도 규칙 폴백이 있어서 서비스 자체는 멀쩡하다."""
    try:
        p = get_provider()
        return {"ok": p.available(), "provider": p.name,
                "fallback": "규칙 기반(rule)", "error": None}
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "provider": settings.llm_provider,
                "fallback": "규칙 기반(rule)", "error": str(e)}


def _resources() -> dict:
    """서버 리소스. psutil을 새로 깔기 싫어서 표준 라이브러리로만 긁는다."""
    res: dict = {"disk": None, "memory": None, "load_avg": None}
    try:
        du = shutil.disk_usage("/")
        res["disk"] = {
            "total_gb": round(du.total / 1024**3, 1),
            "used_gb": round(du.used / 1024**3, 1),
            "free_gb": round(du.free / 1024**3, 1),
            "used_pct": round(100 * du.used / du.total, 1),
        }
    except OSError:
        pass
    try:
        # 리눅스(운영 EC2)에서만 제공 — 맥 로컬에서는 None
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                k, _, v = line.partition(":")
                info[k] = int(v.strip().split()[0])
        total, avail = info["MemTotal"], info.get("MemAvailable", info["MemFree"])
        res["memory"] = {
            "total_mb": round(total / 1024),
            "available_mb": round(avail / 1024),
            "used_pct": round(100 * (total - avail) / total, 1),
        }
    except (OSError, KeyError, ValueError):
        pass
    try:
        res["load_avg"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        pass
    return res


def health(db: Session) -> dict:
    """구성요소 생사와 리소스, 요청 통계. 자동 복구 스크립트도 이걸 본다."""
    dbc, odoo, llm = _check_db(), _check_odoo(), _check_llm()
    uptime = (datetime.now(timezone.utc) - STARTED_AT).total_seconds()

    # DB만 죽어도 서비스는 사실상 정지 → degraded가 아니라 down으로 본다.
    if not dbc["ok"]:
        overall = "down"
    elif not odoo["ok"]:
        overall = "degraded"          # 분석은 되지만 실재고 연동이 끊긴 상태
    else:
        overall = "healthy"

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": round(uptime),
        "uptime_human": _human_uptime(uptime),
        "components": {"database": dbc, "odoo": odoo, "llm": llm},
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pid": os.getpid(),
        },
        "resources": _resources(),
        "requests": log_stats(),
    }


def _human_uptime(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, _ = divmod(s, 60)
    if d:
        return f"{d}일 {h}시간 {m}분"
    if h:
        return f"{h}시간 {m}분"
    return f"{m}분"


# ── 2) 데이터 통계 ──────────────────────────────────────────────

TABLES = [
    ("material", Material, "자재 마스터"),
    ("stock", Stock, "재고"),
    ("material_doc_header", MaterialDocHeader, "자재문서 헤더"),
    ("material_doc_item", MaterialDocItem, "자재문서 항목"),
    ("stock_snapshot_history", StockSnapshotHistory, "재고 스냅샷"),
    ("nfc_tag", NfcTag, "NFC 태그"),
    ("ext_weather", ExtWeather, "외부-날씨"),
    ("ext_holiday", ExtHoliday, "외부-공휴일"),
    ("ext_bid_notice", ExtBidNotice, "외부-입찰공고"),
    ("ext_shop_price", ExtShopPrice, "외부-계약단가"),
    ("equipment", Equipment, "설비 마스터"),
    ("maintenance_order", MaintenanceOrder, "정비오더"),
    ("maintenance_order_part", MaintenanceOrderPart, "정비 사용자재"),
]


def table_stats(db: Session) -> dict:
    """테이블별 행 수와 외부 데이터 최신성. 적재가 빠진 게 있는지 본다."""
    rows = []
    for name, model, label in TABLES:
        try:
            n = db.scalar(select(func.count()).select_from(model)) or 0
        except Exception:                             # noqa: BLE001
            n = None                                   # 테이블 미생성 등
        rows.append({"table": name, "label": label, "rows": n})

    latest_weather = db.scalar(select(func.max(ExtWeather.obs_date)))
    latest_doc = db.scalar(select(func.max(MaterialDocHeader.posting_date)))
    return {
        "tables": rows,
        "freshness": {
            "latest_weather_date": latest_weather,
            "weather_age_days": ((date.today() - latest_weather).days
                                 if latest_weather else None),
            "latest_posting_date": latest_doc,
            "posting_age_days": ((date.today() - latest_doc).days
                                 if latest_doc else None),
        },
    }


# ── 3) 데이터 정합성 점검 ───────────────────────────────────────

def _mk(code: str, name: str, severity: str, bad: int, detail: str,
        action: str, samples: list | None = None) -> dict:
    return {"code": code, "name": name, "severity": severity,
            "passed": bad == 0, "bad_count": bad, "detail": detail,
            "action": action, "samples": samples or []}


def integrity_check(db: Session) -> dict:
    """데이터 정합성을 한 번에 검사한다.

    제일 중요한 건 C01(자재문서 합계 = 재고)이다. 재고를 직접 고치지 않고
    이동의 결과로 집계하니까, 둘이 어긋났다면 이동 없이 재고가 바뀐 것이다.
    수기 UPDATE나 연동 오류를 의심해야 한다.
    """
    checks: list[dict] = []
    today = date.today()

    # C01 — 자재문서 합계 vs 재고 수량
    direction = {m.code: m.direction for m in db.scalars(select(MovementType)).all()}
    moved: dict[tuple, float] = {}
    for mno, pl, sl, mvt, qty in db.execute(
        select(MaterialDocItem.material_no, MaterialDocItem.plant_id,
               MaterialDocItem.sloc_id, MaterialDocItem.movement_type,
               func.sum(MaterialDocItem.quantity))
        .group_by(MaterialDocItem.material_no, MaterialDocItem.plant_id,
                  MaterialDocItem.sloc_id, MaterialDocItem.movement_type)
    ).all():
        key = (mno, pl, sl)
        moved[key] = moved.get(key, 0.0) + float(qty or 0) * direction.get(mvt, 0)

    mismatch = []
    for st in db.scalars(select(Stock)).all():
        key = (st.material_no, st.plant_id, st.sloc_id)
        expected = round(moved.get(key, 0.0), 3)
        actual = round(float(st.unrestricted_qty), 3)
        if abs(expected - actual) > 0.001:
            mismatch.append({"material_no": st.material_no, "plant_id": st.plant_id,
                             "sloc_id": st.sloc_id, "expected": expected,
                             "actual": actual, "diff": round(actual - expected, 3)})
    checks.append(_mk(
        "C01", "자재문서 합계 = 재고 수량", SEV_CRITICAL, len(mismatch),
        "이동유형 방향(±1)×수량의 누계와 stock 테이블 수량이 일치해야 한다. "
        "어긋나면 이동 없이 재고가 바뀐 것이다.",
        "차이 품목의 자재문서를 확인하고, 누락 이동을 전기하거나 재고를 재계산한다.",
        mismatch[:10]))

    # C02 — 음수 재고
    neg = [{"material_no": s.material_no, "qty": float(s.unrestricted_qty)}
           for s in db.scalars(select(Stock).where(Stock.unrestricted_qty < 0)).all()]
    checks.append(_mk(
        "C02", "음수 재고 없음", SEV_CRITICAL, len(neg),
        "가용재고가 0 미만이면 출고 검증을 우회한 전기가 있었다는 뜻이다.",
        "해당 품목의 최근 출고 문서를 취소하거나 재고 실사로 보정한다.", neg[:10]))

    # C03 — 고아 참조(자재문서 → 없는 자재)
    known_mat = {m.material_no for m in db.scalars(select(Material)).all()}
    orphan = sorted({i.material_no for i in db.scalars(select(MaterialDocItem)).all()
                     if i.material_no not in known_mat})
    checks.append(_mk(
        "C03", "고아 참조 없음 (자재문서→자재)", SEV_CRITICAL, len(orphan),
        "자재 마스터에 없는 자재번호를 참조하는 자재문서 항목.",
        "자재 마스터를 복구하거나 해당 문서를 정정 전기한다.",
        [{"material_no": m} for m in orphan[:10]]))

    # C04 — 재주문점 ≥ 안전재고 (논리 정합성)
    bad_rop = [{"material_no": s.material_no,
                "safety_stock": float(s.safety_stock),
                "reorder_point": float(s.reorder_point)}
               for s in db.scalars(select(Stock)).all()
               if float(s.reorder_point) > 0 and float(s.reorder_point) < float(s.safety_stock)]
    checks.append(_mk(
        "C04", "재주문점 ≥ 안전재고", SEV_WARNING, len(bad_rop),
        "ROP = 리드타임 수요 + 안전재고이므로 항상 안전재고보다 크거나 같아야 한다.",
        "/api/reorder/apply 를 다시 실행해 재계산한다.", bad_rop[:10]))

    # C05 — NFC 태그 미매핑 자재
    tagged = {t.material_no for t in db.scalars(select(NfcTag)).all()}
    untagged = sorted(known_mat - tagged)
    checks.append(_mk(
        "C05", "모든 자재에 NFC 태그 매핑", SEV_INFO, len(untagged),
        "태그가 없는 자재는 현장에서 스캔 입출고를 할 수 없다.",
        "nfc_tag 테이블에 UID를 등록한다.",
        [{"material_no": m} for m in untagged[:10]]))

    # C06 — 외부 데이터 최신성 (수집 스케줄이 죽었는지 판단)
    latest_w = db.scalar(select(func.max(ExtWeather.obs_date)))
    stale = 0 if (latest_w and (today - latest_w).days <= 7) else 1
    checks.append(_mk(
        "C06", "외부 날씨 데이터 최신 (7일 이내)", SEV_WARNING, stale,
        f"최근 관측일 {latest_w or '없음'}. 오래되면 수요예측 입력이 낡는다.",
        "scripts/collect_real_data.py 또는 app.scheduler 수집을 다시 돌린다.",
        [{"latest_weather_date": str(latest_w)}] if stale else []))

    # C07 — 완료 정비오더의 부품 전기 누락
    unposted = []
    for o in db.scalars(select(MaintenanceOrder).where(
            MaintenanceOrder.status == "DONE")).all():
        for p in o.parts:
            if p.posted_doc_no is None:
                unposted.append({"order_no": o.order_no, "material_no": p.material_no,
                                 "quantity": float(p.quantity)})
    checks.append(_mk(
        "C07", "완료 정비오더의 부품이 모두 전기됨", SEV_WARNING, len(unposted),
        "완료 처리됐는데 자재문서가 없으면 부품이 장부 없이 사라진 것이다.",
        "해당 오더의 부품을 이동유형 261로 수기 전기한다.", unposted[:10]))

    # C08 — 예방정비 지연 설비
    overdue = []
    for e in db.scalars(select(Equipment).where(Equipment.status != "SCRAP")).all():
        if e.pm_cycle_days and e.last_pm_date:
            due = e.last_pm_date + timedelta(days=e.pm_cycle_days)
            if due < today:
                overdue.append({"equipment_no": e.equipment_no, "name": e.name,
                                "next_pm_date": str(due),
                                "overdue_days": (today - due).days})
    checks.append(_mk(
        "C08", "예방정비 지연 설비 없음", SEV_WARNING, len(overdue),
        "정비가 밀리면 곧 고장(사후정비)으로 이어진다.",
        "정비오더를 등록해 예정일을 다시 잡는다.", overdue[:10]))

    # C09 — 재고 레코드 없는 자재
    stocked = {s.material_no for s in db.scalars(select(Stock)).all()}
    nostock = sorted(known_mat - stocked)
    checks.append(_mk(
        "C09", "모든 자재에 재고 레코드 존재", SEV_INFO, len(nostock),
        "재고 레코드가 없으면 출고가 불가능하고 KPI 집계에서도 빠진다.",
        "stock 레코드를 0으로 생성한다.",
        [{"material_no": m} for m in nostock[:10]]))

    crit = sum(1 for c in checks if not c["passed"] and c["severity"] == SEV_CRITICAL)
    warn = sum(1 for c in checks if not c["passed"] and c["severity"] == SEV_WARNING)
    info = sum(1 for c in checks if not c["passed"] and c["severity"] == SEV_INFO)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "total": len(checks),
        "passed": sum(1 for c in checks if c["passed"]),
        "critical": crit, "warning": warn, "info": info,
        "verdict": ("정상" if crit == 0 and warn == 0
                    else ("주의" if crit == 0 else "위험")),
        "checks": checks,
    }
