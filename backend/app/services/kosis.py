"""통계청 KOSIS 의류 소매판매액지수 수집.

KOSIS는 통계표마다 코드(tblId·itmId·objL)가 달라, KOSIS 통계표 화면의
'OpenAPI(URL 생성)' 기능으로 만든 **전체 URL**(apiKey·기간 포함)을 그대로
.env의 KOSIS_RETAIL_URL 에 넣어 사용한다. 응답 JSON 포맷은 통계표와 무관하게
공통(PRD_DE/DT/C1_NM/ITM_NM/UNIT_NM)이므로 파싱은 한 곳에서 처리한다.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mm import ExtRetailIndex


def _dec(v) -> Decimal | None:
    if v in (None, "", "-"):
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def parse_kosis_response(payload) -> list[dict]:
    """KOSIS 통계자료 JSON(리스트) → 소매판매액지수 레코드."""
    if isinstance(payload, dict):          # 오류 응답({err,errMsg})
        return []
    rows = []
    for it in payload:
        prd = str(it.get("PRD_DE", ""))    # 'YYYYMM'
        if len(prd) != 6:
            continue
        rows.append({
            "period": prd,
            "category": it.get("C1_NM") or it.get("ITM_NM") or "의복",
            "index_value": _dec(it.get("DT")),
            "unit": it.get("UNIT_NM"),
        })
    return rows


def upsert_retail_index(db: Session, rows: list[dict]) -> int:
    for r in rows:
        db.merge(ExtRetailIndex(**r))
    db.commit()
    return len(rows)


def fetch_retail_index(client: httpx.Client | None = None) -> list[dict]:
    """KOSIS_RETAIL_URL 전체 URL을 호출해 파싱. URL 없으면 빈 리스트."""
    if not settings.kosis_retail_url:
        return []
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(settings.kosis_retail_url)
        resp.raise_for_status()
        return parse_kosis_response(resp.json())
    finally:
        if own:
            client.close()


def collect_retail_index(db: Session) -> dict:
    if not settings.kosis_retail_url:
        return {"collected": 0, "has_url": False,
                "message": "KOSIS_RETAIL_URL 미설정 — KOSIS 통계표에서 생성한 OpenAPI URL을 .env에 넣으세요."}
    try:
        rows = fetch_retail_index()
    except httpx.HTTPError as e:
        return {"collected": 0, "has_url": True,
                "message": f"KOSIS 호출 실패: {type(e).__name__} — URL/키/기간을 확인하세요."}
    n = upsert_retail_index(db, rows)
    msg = "수집 완료" if n else "응답은 받았으나 데이터가 없습니다(URL 파라미터/키 권한 확인)."
    return {"collected": n, "has_url": True, "message": msg}
