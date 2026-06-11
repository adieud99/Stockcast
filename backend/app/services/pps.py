"""조달청 종합쇼핑몰 다수공급자계약(MAS) 품목정보 수집 — 실 계약단가.

엔드포인트: apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService/getMASCntrctPrdctInfoList
인증키: settings.pps_api_key (data.go.kr Decoding 키)
용도: 조달청 종합쇼핑몰의 실제 계약단가를 참조 데이터로 적재(우리 품목 단가 검증·비교).
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mm import ExtShopPrice

BASE = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService"
OP = "getMASCntrctPrdctInfoList"


def _dec(v) -> Decimal | None:
    if v in (None, "", "-"):
        return None
    try:
        return Decimal(str(v).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def parse_mas_response(payload: dict) -> list[dict]:
    """MAS 품목 JSON → 계약단가 레코드."""
    body = (payload or {}).get("response", {}).get("body", {})
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    rows = []
    for it in items or []:
        price = _dec(it.get("cntrctPrceAmt"))
        if price is None:
            continue
        rows.append({
            "spec_name": (it.get("prdctSpecNm") or "")[:300] or None,
            "corp_name": it.get("cntrctCorpNm"),
            "maker_name": it.get("prdctMakrNm"),
            "contract_price": price,
            "unit": it.get("prdctUnit"),
            "contract_method": it.get("cntrctMthdNm"),
            "enterprise_div": it.get("entrprsDivNm"),
            "delivery_days": _int(it.get("dlvrTmlmtDaynum")),
        })
    return rows


def fetch_mas_products(begin: date, end: date, rows: int = 100,
                       client: httpx.Client | None = None) -> list[dict]:
    if not settings.pps_api_key:
        return []
    params = {
        "serviceKey": settings.pps_api_key,
        "pageNo": "1", "numOfRows": str(rows), "type": "json",
        "inqryDiv": "1",
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
    }
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        resp = client.get(f"{BASE}/{OP}", params=params)
        resp.raise_for_status()
        return parse_mas_response(resp.json())
    finally:
        if own:
            client.close()


def replace_shop_prices(db: Session, rows: list[dict]) -> int:
    """참조 데이터라 전체 교체(중복 방지)."""
    db.execute(delete(ExtShopPrice))
    for r in rows:
        db.add(ExtShopPrice(**r))
    db.commit()
    return len(rows)


def collect_shop_prices(db: Session, days: int = 7, rows: int = 100) -> dict:
    if not settings.pps_api_key:
        return {"collected": 0, "has_api_key": False,
                "message": "PPS_API_KEY 미설정 — .env에 인증키를 넣으세요."}
    end = date.today()
    begin = end - timedelta(days=days)
    try:
        items = fetch_mas_products(begin, end, rows=rows)
    except httpx.HTTPError as e:
        return {"collected": 0, "has_api_key": True,
                "message": f"종합쇼핑몰 호출 실패: {type(e).__name__} — 키/파라미터 확인."}
    n = replace_shop_prices(db, items)
    msg = "수집 완료" if n else "응답은 받았으나 단가 데이터가 없습니다(기간 확인)."
    return {"collected": n, "has_api_key": True, "message": msg}
