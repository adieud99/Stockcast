# StockCast — SAP 백오피스 NFC 재고관리·수요예측 시스템

NFC로 실물 재고를 자동 기록하고 외부 데이터(날씨·공휴일)로 수요를 예측해,
**SAP MM 모듈 구조를 차용한** 백오피스의 재고·발주 의사결정을 지원하는
AWS 프리 티어 기반 스마트 재고관리 시스템입니다.

> NFC 입출고 자동기록 → SAP 재고 갱신 → 외부데이터 결합 수요예측 → 안전재고·ROP → 발주 권장 → KPI 대시보드 + AI 요약
>
> 단일 기업용 백오피스 PoC · 전체 무료(오픈소스 + AWS 프리티어) 원칙

## 아키텍처 개요

```
[NFC 스캔] ─┐
[외부 공공 API(날씨·공휴일)] ─┼─▶ [FastAPI 백엔드] ─▶ [PostgreSQL (SAP MM 구조)]
                              │           │
                              │           ├─▶ [분석엔진: 다중회귀 수요예측 + 안전재고/ROP]
                              │           └─▶ [로컬 LLM(Ollama) 자연어 해석]
                              ▼
                     [React + Recharts KPI 대시보드]
```

## 기술 스택 (현업 표준 · 비용 0)

| 영역 | 기술 |
|------|------|
| 백엔드 | Python 3.11, FastAPI, SQLAlchemy, Alembic |
| DB | PostgreSQL 16 (SAP MM 구조 차용) |
| 분석/AI | pandas, scikit-learn, statsmodels, Ollama(로컬 LLM) |
| 프론트엔드 | React, Vite, Recharts |
| 인프라 | Docker, Terraform(IaC), GitHub Actions(CI/CD), AWS 프리티어 |

## 디렉터리 구조

```
backend/      FastAPI 애플리케이션 (API, 모델, 서비스)
analytics/    수요예측·재고 로직 (forecast, inventory)
frontend/     React 백오피스 대시보드
db/           스키마 마이그레이션 + 샘플 시드 데이터
infra/        Terraform IaC
docs/         설계 문서
```

## 빠른 시작 (로컬)

```bash
# 1. DB + 백엔드 기동
docker compose up -d db
cp .env.example .env

# 2. 백엔드 의존성 설치 및 실행
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# API 문서: http://localhost:8000/docs
```

## 개발 단계

1. ✅ 프로젝트 구조 + Docker/DB 환경
2. SAP MM 기반 데이터 모델
3. 백엔드 API + NFC 입출고
4. 외부 데이터 수집 (날씨/공휴일)
5. 수요예측 + 재고/발주 로직
6. KPI 대시보드 (React)
7. AI 해석 (Ollama)
8. IaC/CI/CD + AWS 배포
