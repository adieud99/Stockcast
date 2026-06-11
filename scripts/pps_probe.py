"""조달청 종합쇼핑몰 다수공급자계약(MAS) 품목정보 API 원응답 점검.

엔드포인트: apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService/getMASCntrctPrdctInfoList
인증키: .env 의 PPS_API_KEY (data.go.kr Decoding 키)

응답의 item 필드명(계약단가·물품분류명 등)을 확인한 뒤 모델·파서를 확정한다.
실행: docker compose exec -T backend python /workspace/scripts/pps_probe.py
"""
from __future__ import annotations

from datetime import date, timedelta

import httpx

from app.core.config import settings

BASE = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService"
OP = "getMASCntrctPrdctInfoList"


def main() -> None:
    if not settings.pps_api_key:
        print("❌ PPS_API_KEY 미설정 — .env에 인증키를 넣으세요.")
        return
    end = date.today()
    begin = end - timedelta(days=7)
    params = {
        "serviceKey": settings.pps_api_key,
        "pageNo": "1", "numOfRows": "5", "type": "json",
        "inqryDiv": "1",  # 1=등록일자 기준(추정) — 응답 보고 조정
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
    }
    url = f"{BASE}/{OP}"
    print(f"요청: {url}\n기간(등록일자): {begin}~{end}")
    resp = httpx.get(url, params=params, timeout=20)
    print(f"HTTP {resp.status_code}, content-type={resp.headers.get('content-type')}")
    print("\n----- 원응답(앞 2000자) -----")
    print(resp.text[:2000])
    print("\n위 응답의 item 필드명(계약단가·물품분류명 등)을 그대로 붙여주시면 "
          "모델·파서를 정확히 만들겠습니다.")


if __name__ == "__main__":
    main()
