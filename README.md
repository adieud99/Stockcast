# StockCast — NFC·실 공공데이터 기반 공공조달 재고관리 백오피스

🔗 **라이브 데모(HTTPS)**: https://stockcast-yeondong.duckdns.org
· [대시보드](https://stockcast-yeondong.duckdns.org/dashboard)
· [API 문서](https://stockcast-yeondong.duckdns.org/docs)
· Odoo ERP: http://stockcast-yeondong.duckdns.org:8069

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Odoo](https://img.shields.io/badge/Odoo-18_Community-714B67?logo=odoo&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-7B42BC?logo=terraform&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-EC2-FF9900?logo=amazonaws&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue)

**공공조달 납품업체**가 NFC로 실물 재고를 기록하고, 실제 공공데이터(기상청 날씨·공휴일·나라장터 입찰공고·조달청 단가)로 수요를 예측해 발주를 결정하는 **백오피스(내부 운영) 시스템**입니다. 실물 재고·운영은 **실제 ERP(Odoo)** 가 맡고, 수요예측·안전재고·경영분석은 **StockCast 분석 엔진**이 맡아 **API(XML-RPC)로 양방향 연동**합니다.

> NFC 입출고 → Odoo 실재고 갱신 → 실 공공데이터 결합 수요예측 → 안전재고·재주문점 → Odoo 재주문 규칙 반영 → KPI 대시보드 + AI 운영요약

## 아키텍처 — 운영계(OLTP) + 분석계(OLAP) 분리

```
[NFC 스캔(Web NFC)] ─┐
                     ▼
            [StockCast(FastAPI)] ──XML-RPC──▶ [Odoo 18 (실제 ERP / 운영계)]
   ┌──────────────────┤  ◀── 실시간 재고 ──   품목·재고·입출고·재주문규칙
   │                  │
   ▼                  ▼ 재주문점·발주상한 write-back
[StockCast DB(분석계)]   [수요예측·안전재고·ABC·KPI·AI요약]
 1년 거래이력 + 외부공공데이터        │
 (날씨·공휴일·입찰·단가)              ▼
                          [React 대시보드 (KPI·Odoo실재고·NFC)]
                                  ▲ HTTPS(Caddy + Let's Encrypt)
```

- **Odoo = 운영계(system of record):** 지금 이 순간의 실물 재고·입출고·재주문 규칙. 실시간 트랜잭션.
- **StockCast DB = 분석계(데이터 웨어하우스):** 1년치 거래 이력 + 외부 공공데이터를 모아 수요예측·경영분석. 무거운 분석 쿼리를 운영 DB와 분리.
- **양방향 연동:** (정방향) StockCast 재주문점·발주상한 → Odoo 재주문 규칙 / (역방향) Odoo 실재고 → 대시보드.

## 핵심 특징

- **실제 ERP 활용** — Odoo Community(자체 호스팅)로 실물 재고·운영 화면을 그대로 사용. AI·수요예측은 Odoo Enterprise 전용이라, 그 자리를 StockCast가 무료로 대체(차별점).
- **유의미한 실 공공데이터** — 기상청 ASOS 날씨, 한국천문연구원 공휴일, 조달청 나라장터 입찰공고(실수요), 조달청 종합쇼핑몰 MAS 계약단가(실가격). 수요는 실제 기온·강수·휴일에 반응.
- **NFC 입출고** — Web NFC API(안드로이드 크롬·HTTPS)로 실물 태그 태깅 → Odoo 실재고 실시간 입/출고.
- **수요예측 2종** — 품목별 다중회귀(OLS, 해석 가능) + 시계열(Holt-Winters/SARIMA).
- **경영 관점** — 안전재고(SS=Z·σ·√L)·재주문점(ROP)·발주상한, ABC 분석(매출 파레토), 재고자산금액(운전자본), 재고회전율·결품률.
- **AI 운영요약** — 운영현황·수요회전·재고건전성·ABC·권장조치 5관점 근거 서술(LLM/규칙 폴백).
- **현직 표준 인프라** — Docker Compose, Terraform(IaC), AWS EC2(t3.small)+Elastic IP, Caddy 자동 HTTPS, GitHub.

## 기술 스택

| 영역 | 기술 |
|------|------|
| 백엔드 | Python 3.11, FastAPI, SQLAlchemy 2.0, psycopg3 |
| 분석계 DB | PostgreSQL 16 (SAP MM 구조 차용, 15개 엔터티) |
| 운영계 ERP | Odoo 18 Community (PostgreSQL, XML-RPC 연동) |
| 분석 | pandas, statsmodels(OLS·Holt-Winters·SARIMA), 안전재고/ROP |
| AI | LLM provider 추상화 — Gemini(무료등급)/Ollama/규칙 폴백 |
| 프론트엔드 | React + Chart.js (단일 HTML, 백엔드 서빙) |
| 외부데이터 | 공공데이터포털(기상청·특일·나라장터·조달청 종합쇼핑몰), 통계청 KOSIS(선택) |
| 인프라 | Docker Compose, Terraform, AWS EC2+EIP, Caddy(HTTPS), DuckDNS |

## 데이터 모델 (15개 엔터티)

- **마스터/운영:** plant, storage_location, material_group(코드성), material, stock, movement_type(코드성), material_doc_header, material_doc_item, nfc_tag
- **이력성:** stock_snapshot_history(월말 재고 스냅샷)
- **외부 공공데이터:** ext_weather, ext_holiday(코드성), ext_bid_notice(나라장터 입찰), ext_shop_price(조달청 단가), ext_retail_index(KOSIS·선택)

## 빠른 시작 (로컬, Docker)

```bash
cp .env.example .env            # API 키 입력(없어도 동작 — 합성 데이터로 폴백)

# 1) StockCast 기동
docker compose up -d --build

# 2) 실 공공데이터 수집 + 적재
docker compose exec -T backend python /workspace/scripts/collect_real_data.py

# 3) 실제 ERP(Odoo) 기동 + DB 생성(브라우저 localhost:8069) + 재고관리 앱 설치
cd infra/odoo && docker compose -f docker-compose.odoo.yml up -d

# 4) 조달 품목·재고를 Odoo에 적재 + 분석→Odoo 재주문규칙 반영
docker compose exec -T backend python /workspace/scripts/odoo_load.py
docker compose exec -T backend python /workspace/scripts/odoo_sync_reorder.py
```

| 화면 | 주소 |
|------|------|
| 대시보드(홈) | http://localhost:8000/ |
| Odoo ERP | http://localhost:8069/ |
| API 문서(한국어) | http://localhost:8000/docs |

### 운영(실서비스) 주소 — AWS 배포

| 화면 | 주소 |
|------|------|
| 대시보드(홈) | https://stockcast-yeondong.duckdns.org/ |
| API 문서 | https://stockcast-yeondong.duckdns.org/docs |
| Odoo ERP | http://stockcast-yeondong.duckdns.org:8069/ |

## 환경 변수 (.env)

| 키 | 설명 |
|----|------|
| `KMA_API_KEY` / `HOLIDAY_API_KEY` | 공공데이터포털 키(기상청·특일) |
| `NARA_API_KEY` / `PPS_API_KEY` | 나라장터 입찰·조달청 종합쇼핑몰 키 |
| `ODOO_URL/DB/USERNAME/PASSWORD` | Odoo 연동(기본 host.docker.internal:8069) |
| `GEMINI_API_KEY` | AI 요약(없으면 규칙 기반 폴백) |
| `STOCKCAST_DOMAIN` | HTTPS 도메인(Caddy, 예: xxx.duckdns.org) |

## 도메인·HTTPS

운영 환경은 무료 동적 DNS(**DuckDNS**)로 도메인 `stockcast-yeondong.duckdns.org`을 발급받아 EC2 고정 IP(Elastic IP)에 연결했다. **Caddy** 리버스 프록시가 Let's Encrypt 인증서를 자동 발급해 HTTPS를 제공한다. HTTPS는 단순 보안뿐 아니라 **Web NFC API(보안 컨텍스트 필수)** 동작 조건이라, 안드로이드 크롬에서 실물 NFC 태깅을 가능하게 한다.

## 배포 (AWS + HTTPS)

`infra/terraform/`로 EC2(t3.small)+Elastic IP+보안그룹을 IaC로 구성, `infra/caddy/`로 무료 HTTPS(Let's Encrypt). 자세한 설계·기술 의사결정은 **[docs/설계_및_결정.md](docs/설계_및_결정.md)** 참고.

## 테스트

```bash
docker compose exec -T backend pytest -q   # 54건
```

## 라이선스

MIT
