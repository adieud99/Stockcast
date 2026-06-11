"""나라장터 입찰공고 API 원응답 점검 — 파싱 확정 전에 실제 응답을 눈으로 확인.

실행(컨테이너):
  docker compose exec -T backend python /workspace/scripts/nara_probe.py
필요: .env 의 NARA_API_KEY
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import httpx

from app.core.config import settings
from app.services.nara import BID_URL, parse_bid_response


def main() -> None:
    if not settings.nara_api_key:
        print("❌ NARA_API_KEY 미설정 — .env에 인증키를 넣으세요.")
        return
    end = date.today()
    begin = end - timedelta(days=7)
    params = {
        "serviceKey": settings.nara_api_key,
        "pageNo": "1", "numOfRows": "5", "inqryDiv": "1",
        "inqryBgnDt": begin.strftime("%Y%m%d") + "0000",
        "inqryEndDt": end.strftime("%Y%m%d") + "2359",
        "type": "json",
    }
    print(f"요청: {BID_URL}\n기간: {begin}~{end}")
    resp = httpx.get(BID_URL, params=params, timeout=20)
    print(f"HTTP {resp.status_code}, content-type={resp.headers.get('content-type')}")
    text = resp.text
    print("\n----- 원응답(앞 1500자) -----")
    print(text[:1500])
    try:
        payload = resp.json()
        rows = parse_bid_response(payload)
        print(f"\n----- 파싱 결과: {len(rows)}건 -----")
        for r in rows[:3]:
            print(json.dumps(r, ensure_ascii=False, default=str))
    except Exception as e:  # noqa: BLE001
        print(f"\n⚠️ JSON 파싱 실패({type(e).__name__}). 위 원응답이 XML이면 알려주세요 — 파서 조정합니다.")


if __name__ == "__main__":
    main()
