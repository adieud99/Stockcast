"""외부 공공데이터 수집 — 기상청 날씨 + 공휴일.

데이터 출처(공공데이터포털 data.go.kr, 무료):
  - 기상청 ASOS 일자료: AsosDalyInfoService/getWthrDataList
  - 한국천문연구원 특일정보: SpcdeInfoService/getRestDeInfo

설계:
  - HTTP 호출부(fetch_*)와 파싱부(parse_*)를 분리해 파싱을 단위 테스트 가능하게 한다.
  - upsert는 ORM merge로 처리해 멱등성을 보장한다(중복 수집해도 안전).
  - API 키(settings.kma_api_key 등)가 없으면 호출을 건너뛰고 안내한다.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.mm import ExtHoliday, ExtWeather

KMA_URL = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
HOLIDAY_URL = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getRestDeInfo"


def _to_decimal(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


# ---------------- 파싱 (테스트 대상) ----------------
def parse_kma_response(payload: dict) -> list[dict]:
    """기상청 ASOS 일자료 JSON → 날씨 레코드 리스트."""
    items = (payload.get("response", {}).get("body", {})
             .get("items", {}).get("item", []))
    if isinstance(items, dict):
        items = [items]
    rows = []
    for it in items:
        tm = it.get("tm")  # 'YYYY-MM-DD'
        if not tm:
            continue
        rows.append({
            "obs_date": datetime.strptime(tm, "%Y-%m-%d").date(),
            "region_code": str(it.get("stnId", "108")),
            "avg_temp": _to_decimal(it.get("avgTa")),
            "min_temp": _to_decimal(it.get("minTa")),
            "max_temp": _to_decimal(it.get("maxTa")),
            "precip_mm": _to_decimal(it.get("sumRn")) or Decimal(0),
        })
    return rows


def parse_holiday_response(payload: dict) -> list[dict]:
    """특일정보 JSON → 공휴일 레코드 리스트."""
    items = (payload.get("response", {}).get("body", {})
             .get("items", {}).get("item", []))
    if isinstance(items, dict):
        items = [items]
    rows = []
    for it in items:
        locdate = str(it.get("locdate", ""))  # 'YYYYMMDD'
        if len(locdate) != 8:
            continue
        rows.append({
            "holiday_date": datetime.strptime(locdate, "%Y%m%d").date(),
            "name": it.get("dateName", ""),
            "is_holiday": str(it.get("isHoliday", "Y")).upper() == "Y",
        })
    return rows


# ---------------- 적재 (멱등) ----------------
def upsert_weather(db: Session, rows: list[dict]) -> int:
    # 같은 관측일 중복 방어(나중 값이 우선)
    dedup = {r["obs_date"]: r for r in rows}
    for r in dedup.values():
        db.merge(ExtWeather(**r))
    db.commit()
    return len(dedup)


def upsert_holidays(db: Session, rows: list[dict]) -> int:
    # 같은 날짜에 공휴일이 둘 이상이면(예: 어린이날·부처님오신날) 이름을 합쳐 1건으로.
    dedup: dict = {}
    for r in rows:
        d = r["holiday_date"]
        if d in dedup:
            prev = dedup[d]["name"]
            if r["name"] and r["name"] not in prev:
                dedup[d]["name"] = f"{prev}·{r['name']}"[:60]
        else:
            dedup[d] = dict(r)
    for r in dedup.values():
        db.merge(ExtHoliday(**r))
    db.commit()
    return len(dedup)


# ---------------- HTTP 호출 ----------------
def fetch_weather(start: date, end: date, stn_id: str = "108",
                  client: httpx.Client | None = None) -> list[dict]:
    """기상청 ASOS 일자료 수집. API 키 없으면 빈 리스트."""
    if not settings.kma_api_key:
        return []
    params = {
        "serviceKey": settings.kma_api_key, "dataType": "JSON", "dataCd": "ASOS",
        "dateCd": "DAY", "startDt": start.strftime("%Y%m%d"),
        "endDt": end.strftime("%Y%m%d"), "stnIds": stn_id,
        "numOfRows": "999", "pageNo": "1",
    }
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        resp = client.get(KMA_URL, params=params)
        resp.raise_for_status()
        return parse_kma_response(resp.json())
    finally:
        if own:
            client.close()


def fetch_holidays(year: int, month: int | None = None,
                   client: httpx.Client | None = None) -> list[dict]:
    """특일정보(공휴일) 수집. API 키 없으면 빈 리스트."""
    if not settings.holiday_api_key:
        return []
    params = {"serviceKey": settings.holiday_api_key, "solYear": str(year),
              "numOfRows": "100", "_type": "json"}
    if month:
        params["solMonth"] = f"{month:02d}"
    own = client is None
    client = client or httpx.Client(timeout=10)
    try:
        resp = client.get(HOLIDAY_URL, params=params)
        resp.raise_for_status()
        return parse_holiday_response(resp.json())
    finally:
        if own:
            client.close()


def collect_weather(db: Session, start: date, end: date) -> dict:
    """날씨 수집. 외부망 오류가 나도 멈추지 않고 메시지를 반환한다."""
    if not settings.kma_api_key:
        return {"collected": 0, "has_api_key": False,
                "message": "API 키가 설정되지 않았습니다(.env의 KMA_API_KEY)."}
    try:
        rows = fetch_weather(start, end)
    except httpx.HTTPError as e:
        return {"collected": 0, "has_api_key": True,
                "message": f"외부 API 호출 실패: {type(e).__name__} — 키 활성화/네트워크를 확인하세요."}
    n = upsert_weather(db, rows)
    msg = "수집 완료" if n else "응답은 받았으나 데이터가 없습니다(날짜 범위/지점/키 권한 확인)."
    return {"collected": n, "has_api_key": True, "message": msg}


def collect_holidays(db: Session, year: int) -> dict:
    """공휴일 수집. 외부망 오류가 나도 멈추지 않고 메시지를 반환한다."""
    if not settings.holiday_api_key:
        return {"collected": 0, "has_api_key": False,
                "message": "API 키가 설정되지 않았습니다(.env의 HOLIDAY_API_KEY)."}
    try:
        rows = fetch_holidays(year)
    except httpx.HTTPError as e:
        return {"collected": 0, "has_api_key": True,
                "message": f"외부 API 호출 실패: {type(e).__name__} — 키 활성화/네트워크를 확인하세요."}
    n = upsert_holidays(db, rows)
    msg = "수집 완료" if n else "응답은 받았으나 데이터가 없습니다(연도/키 권한 확인)."
    return {"collected": n, "has_api_key": True, "message": msg}
