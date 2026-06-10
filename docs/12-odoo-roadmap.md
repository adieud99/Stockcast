# StockCast 2차 개편 로드맵 — 실제 ERP(Odoo) 연동 · 실 공공데이터

교수님 피드백(① 유의미한 실 공공데이터, ② 실무에 필요한 운영 화면, ③ 실제 ERP 활용 — Odoo)을 반영한 개편 계획.

## 목표 아키텍처

```
[조달청/나라장터 · 기상청 날씨 · 공휴일 (실 공공데이터)]
                 │
                 ▼
        [StockCast 분석엔진] ──XML-RPC──▶ [Odoo Community (실제 ERP)]
        수요예측·안전재고·ABC          ◀── 실물 재고/입출고/조달 ──
                 │                          (재고 추가 등 운영 CRUD 화면)
                 ▼
        [StockCast 대시보드: 예측·발주권고]
```

핵심 분담: **Odoo = 실물 재고·운영 화면(시스템 of record)**, **StockCast = Odoo가 못 주는 무료 수요예측·발주 분석(차별점)**. Odoo의 AI·예측은 유료 Enterprise 전용이므로, 우리 엔진이 그 자리를 무료로 채운다.

## 단계

### A. Odoo 도입 (실제 ERP 백본) — 진행 중
- A1. `infra/odoo/`에 Odoo 18 + 전용 Postgres docker-compose 구성 ✅
- A2. (사용자) DB 생성 + 재고관리(Inventory) 앱 설치 + API 키 발급
- A3. 연결 확인(`scripts/odoo_ping.py`)

### B. 상품·재고 적재
- 우리 29종 의류 → Odoo product.template/카테고리, 창고/위치, 초기 재고(stock.quant) 적재(XML-RPC)

### C. StockCast ↔ Odoo 연동
- `odoo_client.py`(xmlrpc): 상품·재고(stock.quant)·이동(stock.move) 읽기
- 분석 입력을 Odoo 실데이터로 전환
- 안전재고·발주권고를 Odoo에 write-back(재주문 규칙/활동)

### D. 실 공공데이터
- 기상청 날씨·공휴일 1년치 실수집(기존 커넥터 활용)
- 조달청/나라장터 단가·조달 커넥터 신규 + 예측 피처 반영

### E. 화면·문서 마무리
- 홈에 Odoo 재고화면 + StockCast 분석 대시보드 공존
- README 갱신, 인프라 강점 설명 + 발표용 최종 설명 문서

## 비용·인프라 메모
- Odoo Community = 소프트웨어 비용 0(LGPL v3). 스택이 Python+PostgreSQL+Docker라 기존 인프라 재사용.
- t3.micro(1GB)는 Odoo에 빠듯 → 개발·시연은 맥 로컬, AWS는 스왑 추가(무료). 불안정 시 t3.small.
