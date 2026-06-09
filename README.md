# StockCast — SAP 백오피스 NFC 재고관리·수요예측 시스템

🔗 **라이브 데모**: http://43.201.255.8:8000/  ·  [대시보드](http://43.201.255.8:8000/dashboard)  ·  [API 문서](http://43.201.255.8:8000/docs)

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?logo=sqlalchemy&logoColor=white)
![pandas](https://img.shields.io/badge/pandas-150458?logo=pandas&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-F7931E?logo=scikitlearn&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?logo=react&logoColor=black)
![Chart.js](https://img.shields.io/badge/Chart.js-FF6384?logo=chartdotjs&logoColor=white)
![Gemini](https://img.shields.io/badge/Google%20Gemini-8E75B2?logo=googlegemini&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![Terraform](https://img.shields.io/badge/Terraform-7B42BC?logo=terraform&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![AWS](https://img.shields.io/badge/AWS-EC2-FF9900?logo=amazonaws&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-blue)

NFC로 실물 재고를 자동 기록하고 외부 데이터(날씨·공휴일)로 수요를 예측해,
**SAP MM 모듈 구조를 차용한** 백오피스의 재고·발주 의사결정을 지원하는
AWS 프리 티어 기반 스마트 재고관리 시스템입니다.

> NFC 입출고 자동기록 → SAP 재고 갱신 → 외부데이터 결합 수요예측 → 안전재고·ROP → 발주 권장 → KPI 대시보드 + AI 요약
>
> 단일 기업용 백오피스 PoC · 전체 무료(오픈소스 + 클라우드 무료등급 + AWS 프리티어) 원칙

## 아키텍처 개요

```
[NFC 스캔] ─┐
[외부 공공 API(날씨·공휴일)] ─┼─▶ [FastAPI 백엔드] ─▶ [PostgreSQL (SAP MM 구조)]
                              │           │
                              │           ├─▶ [분석엔진: 다중회귀 수요예측 + 안전재고/ROP]
                              │           └─▶ [LLM 자연어 해석 (Gemini/Ollama, 규칙 폴백)]
                              ▼
                     [React + Chart.js KPI 대시보드]
```

## 기술 스택 (현업 표준 · 비용 0)

| 영역 | 기술 |
|------|------|
| 백엔드 | Python 3.11, FastAPI, SQLAlchemy, psycopg |
| DB | PostgreSQL 16 (SAP MM 구조 차용, 12개 엔터티) |
| 분석 | pandas, scikit-learn, statsmodels (품목별 다중회귀) |
| AI | LLM provider 추상화 — Gemini(무료등급, 기본) / Ollama(로컬) / 규칙 기반 폴백 |
| 프론트엔드 | React + Chart.js (단일 파일, 백엔드가 서빙) |
| 인프라 | Docker, Docker Compose, Terraform(IaC), GitHub Actions(CI/CD), AWS 프리티어(EC2) |

## 디렉터리 구조

```
backend/      FastAPI 애플리케이션 (API, 모델, 서비스, 테스트)
analytics/    수요예측·재고 로직 (forecast, inventory)
frontend/     대시보드·NFC 입출고 화면 (HTML/React)
db/           스키마 마이그레이션 + 시드 (SQL + ORM 시더)
infra/        Terraform IaC
docs/         설계·산출물 문서 (ERD, 정의서, 배포 가이드)
.github/      CI/CD 워크플로
```

## 빠른 시작 (로컬, Docker)

> 맥/윈도우 모두 Docker Desktop만 있으면 됩니다. 파이썬을 따로 설치할 필요 없어요.

```bash
cp .env.example .env     # 필요시 API 키 입력 (없어도 동작)

make up      # DB + 백엔드 컨테이너 기동 (최초 1회 이미지 빌드)
make seed    # 1년치 샘플 데이터 적재
make test    # 테스트 실행 (45건)
```

기동 후 접속:

| 화면 | 주소 |
|------|------|
| 홈 | http://localhost:8000/ |
| KPI 대시보드 | http://localhost:8000/dashboard |
| NFC 입출고 | http://localhost:8000/nfc |
| API 문서(한국어) | http://localhost:8000/docs |

## 환경 변수 (.env)

| 키 | 설명 |
|----|------|
| `LLM_PROVIDER` | `gemini`(기본) / `ollama` / `rule` |
| `GEMINI_API_KEY` | Google AI Studio 무료 키 (없으면 규칙 기반 폴백) |
| `KMA_API_KEY` / `HOLIDAY_API_KEY` | 공공데이터포털 키 (없으면 시드 데이터 사용) |

## 개발 단계 (12주)

1. ✅ 프로젝트 구조 + Docker/DB 환경
2. ✅ SAP MM 기반 데이터 모델 (12개 엔터티)
3. ✅ 백엔드 API + NFC 입출고
4. ✅ 외부 데이터 수집 (날씨/공휴일)
5. ✅ 데이터 전처리·EDA + 상관분석
6. ✅ 수요예측 (품목별 다중회귀)
7. ✅ 안전재고·재주문점(ROP) 발주 로직
8. ✅ KPI 대시보드
9. ✅ AI 자연어 해석 (Gemini/Ollama)
10. ✅ IaC/CI/CD + AWS 배포 코드
11. ⬜ 통합 테스트
12. ⬜ 마무리·발표자료

## 배포

`infra/terraform/`의 Terraform으로 AWS EC2(프리티어)에 배포한다. 자세한 절차는
[docs/10-deployment.md](docs/10-deployment.md) 참고.

## 라이선스

MIT
