.PHONY: up down seed test logs reset ps

# 1) 전체 기동 (DB + 백엔드). 최초 1회는 백엔드 이미지 빌드(수 분).
#    DB 최초 기동 시 db/migrations/*.sql 자동 적용(스키마 + 마스터 시드).
#    백엔드는 컨테이너 내 Python 3.11에서 자동 실행 → http://localhost:8000/docs
up:
	docker compose up -d --build
	@echo ""
	@echo "기동 완료. 다음: make seed  (1년치 데이터 적재)"
	@echo "API 문서: http://localhost:8000/docs"

# 2) 시계열 거래/날씨 시드 적재 (백엔드 컨테이너 안에서 실행)
seed:
	docker compose exec backend python /workspace/db/seeds/seed_transactions.py

# 테스트 (백엔드 컨테이너 안에서, SQLite 인메모리)
test:
	docker compose exec backend python -m pytest -q

logs:
	docker compose logs -f backend

ps:
	docker compose ps

# DB 초기화 (볼륨 삭제 후 재기동 → 스키마/마스터 재적용)
reset:
	docker compose down -v
	docker compose up -d --build

down:
	docker compose down
