"""조달청 나라장터 입찰공고정보서비스(물품) 수집 — 실제 조달 수요 신호.

엔드포인트: apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoThng
인증키: settings.nara_api_key (data.go.kr Decoding 키)
응답 포맷/날짜 파라미터는 서비스 버전에 따라 차이가 있어, 먼저 scripts/nara_probe.py 로
원응답을 확인한 뒤 파싱을 확정한다(파서는 방어적으로 작성).
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mm import ExtBidNotice

BID_URL = ("https://apis.data.go.kr/1230000/ad/BidPublicInfoService/"
           "getBidPblancListInfoThng")


def _dec(v) -> Decimal | None:
    if v in (None, "", "-"):
        return None
    try:
        return Decimal(str(v).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _parse_dt(v) -> date | None:
    if not v:
        return None
    txt = str(v).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(txt[:len(fmt) + 2 if "%H" in fmt else 10], fmt).date()
        except ValueError:
            continue
    return None


def parse_bid_response(payload: dict) -> list[dict]:
    """입찰공고 JSON → 레코드. items 위치/형태가 달라도 견디도록 처리."""
    body = (payload or {}).get("response", {}).get("body", {})
    items = body.get("items", [])
    if isinstance(items, dict):
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    rows = []
    for it in items or []:
        no = str(it.get("bidNtceNo", "")).strip()
        if not no:
            continue
        rows.append({
            "bid_no": no,
            "bid_ord": (str(it.get("bidNtceOrd", "00")).strip() or "00"),
            "bid_name": (it.get("bidNtceNm") or "")[:300] or None,
            "notice_agency": it.get("ntceInsttNm"),
            "demand_agency": it.get("dminsttNm"),
            "est_price": _dec(it.get("presmptPrc") or it.get("asignBdgtAmt")),
            "notice_date": _parse_dt(it.get("bidNtceDt") or it.get("bidNtceDate")
                                     or it.get("rgstDt")),
            "category": "물품",
        })
    return rows


def fetch_bid_notices(begin: date, end: date, rows: int = 100,
                      client: httpx.Client | None = None) -> list[dict]:
    """기간 내 물품 입찰공고 수집. 키 없으면 빈 리스트."""
    if not settings.nara_api_key:
        return []
    params = {
        "serviceKey": settings.nara_api_key,
        "pageNo": "1", "numOfRows": str(rows),
        "inqryDiv": "1",  # 1=공고게시일시 기준
        "inqryBgnDt": begin.strftime("%Y%m%d") + "0000",
        "inqryEndDt": end.strftime("%Y%m%d") + "2359",
        "type": "json",
    }
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        resp = client.get(BID_URL, params=params)
        resp.raise_for_status()
        return parse_bid_response(resp.json())
    finally:
        if own:
            client.close()


def upsert_bid_notices(db: Session, rows: list[dict]) -> int:
    for r in rows:
        db.merge(ExtBidNotice(**r))
    db.commit()
    return len(rows)


def collect_bid_notices(db: Session, begin: date, end: date, rows: int = 100) -> dict:
    if not settings.nara_api_key:
        return {"collected": 0, "has_api_key": False,
                "message": "NARA_API_KEY 미설정 — .env에 나라장터 인증키를 넣으세요."}
    try:
        items = fetch_bid_notices(begin, end, rows=rows)
    except httpx.HTTPError as e:
        return {"collected": 0, "has_api_key": True,
                "message": f"나라장터 호출 실패: {type(e).__name__} — 키/파라미터를 확인하세요."}
    n = upsert_bid_notices(db, items)
    msg = "수집 완료" if n else "응답은 받았으나 데이터가 없습니다(기간/응답포맷 확인 — nara_probe 참고)."
    return {"collected": n, "has_api_key": True, "message": msg}
