"""조달청 종합쇼핑몰 품목정보 API 원응답 점검.

이 서비스는 공식 명세가 JS 렌더라 오퍼레이션명·파라미터를 코드로 확정하기 어렵다.
data.go.kr 의 15129471 서비스 페이지에서 원하는 오퍼레이션의 '미리보기/실행'으로
나오는 **전체 요청 URL**(serviceKey 포함)을 복사해 .env 의 PPS_SHOP_URL 에 넣고 실행한다.

실행:
  docker compose exec -T backend python /workspace/scripts/pps_probe.py
"""
from __future__ import annotations

import httpx

from app.core.config import settings


def main() -> None:
    url = settings.pps_shop_url
    if not url:
        print("❌ PPS_SHOP_URL 미설정.")
        print("   data.go.kr 15129471 페이지에서 오퍼레이션 '미리보기'의 전체 요청 URL을")
        print("   복사해 .env 의 PPS_SHOP_URL 에 넣어주세요(serviceKey 포함).")
        return
    print(f"요청: {url[:120]}…")
    resp = httpx.get(url, timeout=20)
    print(f"HTTP {resp.status_code}, content-type={resp.headers.get('content-type')}")
    print("\n----- 원응답(앞 1800자) -----")
    print(resp.text[:1800])
    print("\n위 응답(특히 item 안의 필드명)을 그대로 붙여주시면 모델·파서를 정확히 만들겠습니다.")


if __name__ == "__main__":
    main()
