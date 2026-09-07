.PHONY: up down seed test logs reset ps real health check \
        up-rds tf-plan tf-validate aws-status aws-start aws-stop aws-cost

# RDS 모드로 돌고 있으면 compose 파일이 두 개다.
# user_data 가 /etc/stockcast.env 에 조합을 적어 두므로 있으면 그걸 따른다.
# 이걸 안 보고 base 만 쓰면 서버에서 make up 을 칠 때 DATABASE_URL 이
# @db:5432 로 덮여서 앱이 RDS 를 버리고 빈 컨테이너 DB 를 보게 된다.
# 로컬에는 이 파일이 없으니 지금까지처럼 base 하나만 쓴다.
COMPOSE_FILES ?= $(shell [ -f /etc/stockcast.env ] && . /etc/stockcast.env && printf '%s' "$$COMPOSE_FILES")
COMPOSE := docker compose $(COMPOSE_FILES)

# 1) 전체 기동 (DB + 백엔드). 최초 1회는 백엔드 이미지 빌드(수 분).
up:
	$(COMPOSE) up -d --build
	@echo ""
	@echo "기동 완료. 다음: make seed  (1년치 데이터 적재)"
	@echo "대시보드: http://localhost:8000/    API 문서: http://localhost:8000/docs"

# 2) 테이블 생성 + 시드 적재 (합성 데이터)
#    품목·거래, 설비·정비이력, 안전재고/ROP 반영까지 한 번에 돈다
seed:
	$(COMPOSE) exec -T backend python init_db.py

# 2') 공공데이터로 적재 (기상청·특일·나라장터·조달청). 키 없으면 건너뛰고 합성으로 보정
real:
	$(COMPOSE) exec -T backend python /workspace/scripts/collect_real_data.py

# 테스트 (SQLite 인메모리라 외부 DB나 키가 필요 없다)
test:
	$(COMPOSE) exec -T backend python -m pytest -q

# 운영 상태 점검 (healthy / degraded / down)
health:
	@curl -s localhost:8000/api/ops/health | python3 -m json.tool | head -20

# 데이터 정합성 점검 (9항목)
check:
	@curl -s localhost:8000/api/ops/integrity | python3 -c \
	  "import json,sys;d=json.load(sys.stdin);print(f\"판정: {d['verdict']} ({d['passed']}/{d['total']} 통과)\");[print(f\"  [{c['severity']}] {c['code']} {c['name']} — {c['bad_count']}건\") for c in d['checks'] if not c['passed']]"

logs:
	$(COMPOSE) logs -f backend

ps:
	$(COMPOSE) ps

# DB 초기화 (볼륨 삭제 후 재기동 → 스키마/마스터 재적용)
reset:
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

# ── AWS 운영 (3단계) ────────────────────────────────────────

# RDS를 보도록 기동. .env 의 RDS_DATABASE_URL 을 먼저 채워야 한다.
up-rds:
	docker compose -f docker-compose.yml -f docker-compose.rds.yml up -d

# 인프라 코드 검사 (AWS 자격증명 불필요)
tf-validate:
	terraform -chdir=infra/terraform fmt -check -recursive
	terraform -chdir=infra/terraform validate

# 무엇이 바뀌는지 먼저 본다. 읽기 전용.
tf-plan:
	terraform -chdir=infra/terraform plan

# 서버 상태와 이번 달 비용
aws-status:
	@./scripts/aws_server.sh status

aws-start:
	@./scripts/aws_server.sh start

aws-stop:
	@./scripts/aws_server.sh stop

aws-cost:
	@./scripts/aws_server.sh cost
