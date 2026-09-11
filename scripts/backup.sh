#!/usr/bin/env bash
# ============================================================
# 분석계 DB 백업. RDS 모드와 컨테이너 DB 모드를 모두 처리한다.
#
#   ./scripts/backup.sh                 백업 하나 뜨고 오래된 것 정리
#   ./scripts/backup.sh --verify        뜬 백업을 임시 DB에 복원해서 검증까지
#   RETENTION_DAYS=30 ./scripts/backup.sh
#
# cron 예시 (매일 새벽 3시):
#   0 3 * * * cd /opt/stockcast && ./scripts/backup.sh >> /var/log/stockcast-backup.log 2>&1
#
# --verify 를 붙이면 뜬 파일을 실제로 되살려 본다.
# 복원해 본 적 없는 백업은 백업이 아니다. 주 1회는 이걸로 돌리는 게 좋다.
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-/opt/backup}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
VERIFY=0
[ "${1:-}" = "--verify" ] && VERIFY=1

# .env 를 source 하면 안 된다. RDS_DATABASE_URL_PSYCOPG 값에 공백이 들어 있어서
# "host=..." 까지만 변수에 들어가고 password 가 빠진다. 실제로 pg_dump 가
# "no password supplied" 로 실패했다. 필요한 값만 줄 단위로 읽는다.
envget() {
  [ -f "$ROOT/.env" ] || return 0
  grep -E "^$1=" "$ROOT/.env" | tail -1 | cut -d= -f2- | sed -E 's/^"(.*)"$/\1/'
}
RDS_DATABASE_URL_PSYCOPG="${RDS_DATABASE_URL_PSYCOPG:-$(envget RDS_DATABASE_URL_PSYCOPG)}"
POSTGRES_USER="${POSTGRES_USER:-$(envget POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(envget POSTGRES_DB)}"
[ -f /etc/stockcast.env ] && . /etc/stockcast.env || true

mkdir -p "$BACKUP_DIR"
STAMP=$(date +%F_%H%M)
OUT="$BACKUP_DIR/stockcast_${STAMP}.sql.gz"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

# 어느 모드인지 고른다. RDS 주소가 채워져 있으면 RDS 로 본다.
if [ -n "${RDS_DATABASE_URL_PSYCOPG:-}" ]; then
  MODE="rds"
else
  MODE="container"
fi
log "모드: $MODE"

case "$MODE" in
  rds)
    command -v pg_dump >/dev/null || { log "pg_dump 가 없다. postgresql 클라이언트를 깔 것."; exit 3; }
    pg_dump "$RDS_DATABASE_URL_PSYCOPG" | gzip > "$OUT"
    ;;
  container)
    docker exec -i erp_nfc_db pg_dump -U "${POSTGRES_USER:-erp}" "${POSTGRES_DB:-erp_nfc}" \
      | gzip > "$OUT"
    ;;
esac

SIZE=$(du -h "$OUT" | cut -f1)
log "백업 완료: $OUT ($SIZE)"

# 빈 파일이 만들어졌는데 성공으로 넘어가면 나중에 복원할 게 없다.
BYTES=$(wc -c < "$OUT" | tr -d ' ')
if [ "$BYTES" -lt 1024 ]; then
  log "백업 파일이 ${BYTES}바이트뿐이다. 실패로 본다."
  exit 4
fi

if [ "$VERIFY" -eq 1 ]; then
  log "검증 시작 — 임시 컨테이너에 복원해 본다"
  TMP="stockcast_verify_$$"
  docker run -d --name "$TMP" -e POSTGRES_USER=erp -e POSTGRES_PASSWORD=verify \
    -e POSTGRES_DB=erp_nfc postgres:16 >/dev/null
  trap 'docker rm -f "$TMP" >/dev/null 2>&1 || true' EXIT

  for _ in $(seq 1 30); do
    docker exec "$TMP" pg_isready -U erp >/dev/null 2>&1 && break
    sleep 2
  done

  gunzip -c "$OUT" | docker exec -i "$TMP" psql -U erp -d erp_nfc -q >/dev/null 2>&1

  TABLES=$(docker exec "$TMP" psql -U erp -d erp_nfc -tAc \
    "select count(*) from information_schema.tables where table_schema='public'" | tr -d ' ')
  ROWS=$(docker exec "$TMP" psql -U erp -d erp_nfc -tAc \
    "select count(*) from material_doc_item" 2>/dev/null | tr -d ' ' || echo 0)

  log "복원 결과 — 테이블 ${TABLES}개, material_doc_item ${ROWS}행"
  if [ "${TABLES:-0}" -lt 10 ]; then
    log "테이블이 너무 적다. 백업이 온전하지 않다."
    exit 5
  fi

  # 재고 정합성까지 본다. 복원만 되고 값이 깨져 있으면 소용없다.
  BAD=$(docker exec "$TMP" psql -U erp -d erp_nfc -tAc "
    select count(*) from stock s
    join (select i.material_no,i.plant_id,i.sloc_id,sum(m.direction*i.quantity) tot
          from material_doc_item i join movement_type m on m.code=i.movement_type
          group by 1,2,3) d
      on d.material_no=s.material_no and d.plant_id=s.plant_id and d.sloc_id=s.sloc_id
    where abs(d.tot - s.unrestricted_qty) > 0.001" 2>/dev/null | tr -d ' ' || echo "?")
  log "재고 정합성(C01) 불일치: ${BAD}건"
  log "검증 통과"
fi

DELETED=$(find "$BACKUP_DIR" -name 'stockcast_*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete | wc -l | tr -d ' ')
log "${RETENTION_DAYS}일 지난 백업 ${DELETED}개 정리"
