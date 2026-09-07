#!/usr/bin/env bash
# ============================================================
# 분석계 DB를 RDS로 옮긴다.
#
#   ./scripts/migrate_to_rds.sh \
#       --target "host=stockcast-db.xxx.ap-northeast-2.rds.amazonaws.com port=5432 \
#                 dbname=erp_nfc user=erp password=****"
#
# 원본은 기본적으로 로컬 docker 의 erp_nfc_db 컨테이너다.
# 다른 곳에서 뽑으려면 --source 에 libpq 접속 문자열을 준다.
#
# 순서는 덤프 → 적재 → 대조다. 마지막 대조가 핵심이다.
# pg_restore 는 일부 실패해도 0을 반환할 때가 있어서, 옮겨졌다는 말만 믿으면 안 된다.
# 테이블별 행 수를 양쪽에서 세어 하나라도 다르면 실패로 끝낸다.
# ============================================================
set -euo pipefail

SOURCE_MODE="docker"
SOURCE_CONN=""
TARGET_CONN=""
DUMP_DIR="${DUMP_DIR:-./.migrate}"
PG_IMAGE=""
CONTAINER="${CONTAINER:-erp_nfc_db}"
DB_NAME="${DB_NAME:-erp_nfc}"
DB_USER="${DB_USER:-erp}"
FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --target) TARGET_CONN="$2"; shift 2 ;;
    --source) SOURCE_MODE="conn"; SOURCE_CONN="$2"; shift 2 ;;
    --force)  FORCE=1; shift ;;
    --pg-image) PG_IMAGE="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "모르는 옵션: $1" >&2; exit 2 ;;
  esac
done

[ -n "$TARGET_CONN" ] || { echo "--target 이 필요하다 (RDS libpq 접속 문자열)" >&2; exit 2; }

for c in pg_dump pg_restore psql; do
  command -v "$c" >/dev/null || { echo "$c 가 없다. postgresql-client 를 설치할 것." >&2; exit 3; }
done

# pg_restore 를 컨테이너로 돌릴지 호스트 것으로 돌릴지.
# --pg-image 를 주면 그 이미지 안의 pg_restore 를 쓴다.
run_restore() {
  if [ -n "$PG_IMAGE" ]; then
    docker run --rm -i --network host -v "$(cd "$(dirname "$1")" && pwd):/d" "$PG_IMAGE" \
      pg_restore --no-owner --no-acl --exit-on-error -d "$TARGET_CONN" "/d/$(basename "$1")"
  else
    pg_restore --no-owner --no-acl --exit-on-error -d "$TARGET_CONN" "$1"
  fi
}

mkdir -p "$DUMP_DIR"
DUMP="$DUMP_DIR/erp_nfc_$(date +%Y%m%d_%H%M%S).dump"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

# 원본에 SQL 을 던지는 방법이 두 가지다.
# 주의: 조회에 stdin 을 쓰면 안 된다.
# docker exec -i 는 stdin 을 통째로 읽어가서, 루프 안에서 호출하면
# 루프에 먹여 둔 목록까지 같이 삼킨다. 실제로 18개 중 1개만 대조하고
# "모두 일치"로 끝나는 일이 있었다. 그래서 -i 를 빼고 </dev/null 로 막는다.
src_psql() {
  if [ "$SOURCE_MODE" = "docker" ]; then
    docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -tAc "$1" </dev/null
  else
    psql "$SOURCE_CONN" -tAc "$1" </dev/null
  fi
}
dst_psql() { psql "$TARGET_CONN" -tAc "$1" </dev/null; }

# ── 0) 양쪽 연결 확인 ───────────────────────────────────────
cat <<'WARN'

  옮기기 전에 원본 정합성을 먼저 봐 두는 게 좋다.
      curl -s localhost:8000/api/ops/integrity | python3 -m json.tool
  이 스크립트는 원본을 "그대로" 옮긴다. 원본이 어긋나 있으면 어긋난 채로 간다.
  행 수가 다 맞아도 데이터가 맞다는 뜻은 아니다.

WARN

say "0) 연결 확인"
src_psql "select 1" >/dev/null && echo "  원본 OK"
dst_psql "select 1" >/dev/null && echo "  대상 OK ($(dst_psql "select version()" | cut -c1-40)...)"

# 클라이언트가 서버보다 새로우면 덤프에 서버가 모르는 SET 구문이 섞여 적재가 깨진다.
# 예: pg_restore 18 이 SET transaction_timeout 을 넣는데 PostgreSQL 16 은 이 파라미터를 모른다.
# SQL 에러로 중간에 터지는 것보다 먼저 걸러내는 편이 낫다.
if [ -z "$PG_IMAGE" ]; then
  SRV_MAJOR=$(dst_psql "show server_version" | cut -d. -f1 | tr -d ' ')
  CLI_MAJOR=$(pg_restore --version | grep -oE '[0-9]+' | head -1)
  if [ -n "$SRV_MAJOR" ] && [ -n "$CLI_MAJOR" ] && [ "$CLI_MAJOR" -gt "$SRV_MAJOR" ]; then
    cat >&2 <<EOM
  pg_restore 가 ${CLI_MAJOR} 인데 대상 서버는 ${SRV_MAJOR} 다.
  새 클라이언트가 만든 구문을 옛 서버가 모르면 적재가 중간에 깨진다.

  둘 중 하나로 푼다.
    1) 서버와 같은 버전 클라이언트를 쓴다   (예: dnf install postgresql${SRV_MAJOR})
    2) 컨테이너로 우회한다                  --pg-image postgres:${SRV_MAJOR}
EOM
    exit 7
  fi
  echo "  버전 확인 OK (클라이언트 ${CLI_MAJOR} / 서버 ${SRV_MAJOR})"
fi

# 대상이 비어 있는지 본다. 데이터가 있는데 그냥 부으면 중복되거나 충돌한다.
EXISTING=$(dst_psql "select count(*) from information_schema.tables where table_schema='public'")
if [ "${EXISTING:-0}" -gt 0 ] && [ "$FORCE" -eq 0 ]; then
  echo "  대상에 이미 public 테이블이 ${EXISTING}개 있다. 덮어쓰려면 --force 를 줄 것." >&2
  exit 4
fi

# ── 1) 덤프 ────────────────────────────────────────────────
say "1) 덤프"
if [ "$SOURCE_MODE" = "docker" ]; then
  docker exec -i "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --no-owner --no-acl > "$DUMP"
else
  pg_dump "$SOURCE_CONN" -Fc --no-owner --no-acl > "$DUMP"
fi
echo "  $DUMP ($(du -h "$DUMP" | cut -f1))"

# 옮기기 전 원본 행 수를 적어 둔다.
BEFORE=$(src_psql "
  select relname||'='||n_live_tup
  from pg_stat_user_tables order by relname")
echo "  원본 테이블 $(echo "$BEFORE" | grep -c . )개"

# ── 2) 적재 ────────────────────────────────────────────────
say "2) RDS 적재"
# --no-owner: RDS 는 슈퍼유저를 안 주므로 소유자 지정이 있으면 실패한다.
# --clean 은 일부러 안 쓴다. 실수로 남의 스키마를 지우지 않게.
set +e
run_restore "$DUMP"
RC=$?
set -e
[ $RC -eq 0 ] || { echo "  pg_restore 실패 (rc=$RC)" >&2; exit 5; }
echo "  적재 완료"

# 통계를 새로 계산해야 행 수 비교가 맞는다.
dst_psql "analyze" >/dev/null

# ── 3) 대조 ────────────────────────────────────────────────
say "3) 행 수 대조"
MISMATCH=0
CHECKED=0
# 테이블 이름에는 공백이 없으므로 단어 분리로 순회해도 안전하다.
TABLES=$(echo "$BEFORE" | sed 's/=.*//' | grep -v '^$')
for t in $TABLES; do
  sc=$(src_psql "select count(*) from \"$t\"" | tr -d ' \n')
  dc=$(dst_psql "select count(*) from \"$t\"" | tr -d ' \n')
  CHECKED=$((CHECKED+1))
  if [ "$sc" = "$dc" ]; then
    printf '  %-28s %8s  일치\n' "$t" "$sc"
  else
    printf '  %-28s 원본 %s / 대상 %s  \033[31m불일치\033[0m\n' "$t" "$sc" "$dc"
    MISMATCH=$((MISMATCH+1))
  fi
done

# 원본 테이블 수와 실제 대조한 수가 같아야 한다.
# 하나라도 조용히 건너뛰면 검증이 검증이 아니다.
EXPECTED=$(echo "$TABLES" | grep -c .)
if [ "$CHECKED" -ne "$EXPECTED" ]; then
  echo "  대조한 테이블이 ${CHECKED}개인데 원본은 ${EXPECTED}개다. 목록을 읽다 끊겼다." >&2
  exit 6
fi
echo "  ── ${CHECKED}개 테이블 대조함"

echo
if [ "$MISMATCH" -gt 0 ]; then
  echo "테이블 ${MISMATCH}개가 안 맞는다. 전환하지 말고 원인을 볼 것." >&2
  exit 6
fi

say "완료"
cat <<MSG
모든 테이블 행 수가 일치한다. 다음으로 할 일:

  1) .env 에 아래 두 줄을 넣는다 (terraform output 으로 값을 얻는다)
       RDS_DATABASE_URL=postgresql+psycopg://erp:****@<엔드포인트>:5432/erp_nfc
       RDS_DATABASE_URL_PSYCOPG=host=<엔드포인트> port=5432 dbname=erp_nfc user=erp password=****

  2) RDS 를 보도록 앱을 다시 띄운다
       docker compose -f docker-compose.yml -f docker-compose.rds.yml up -d

  3) 확인 — 두 가지를 다 본다
       curl -s localhost:8000/api/ops/health    | python3 -m json.tool
       curl -s localhost:8000/api/ops/integrity | python3 -m json.tool

     health 는 "붙었나"를 보고, integrity 는 "데이터가 맞나"를 본다.
     행 수 대조를 통과해도 integrity 가 깨질 수 있다. 그건 옮기다 생긴 게 아니라
     원본이 원래 그랬던 것이므로, 옮기기 전 값과 비교해서 판단한다.

  4) 며칠 지켜본 뒤 문제 없으면 옛 볼륨을 지운다
       docker volume rm \$(docker volume ls -q | grep pgdata)

덤프 파일은 $DUMP 에 남겨 뒀다. 되돌릴 때 쓴다.
MSG
