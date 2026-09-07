#!/usr/bin/env bash
# ============================================================
# StockCast 헬스 워치독
#
# /health 가 죽어 있으면 단계적으로 되살린다.
#   1차 실패 → backend 컨테이너만 재시작 (빠르고 영향이 작다)
#   2차 실패 → compose 전체 재기동
#   그 뒤로도 실패 → 손대지 않고 로그만 남긴다
#
# 마지막 단계에서 멈추는 게 중요하다. 계속 재시작하면 로그가 덮이고
# 원인을 볼 수 없게 된다. 사람이 봐야 하는 상황을 사람에게 넘긴다.
#
# 얕은 /health 를 쓰는 이유:
#   /health          프로세스가 살아 있나 (liveness). 여기서 쓴다.
#   /api/ops/health  DB·Odoo·LLM 까지 본다 (readiness). 감시용이지 재시작 기준이 아니다.
# 깊은 쪽을 재시작 기준으로 삼으면 RDS가 잠깐 느려질 때마다 앱을 껐다 켠다.
# ============================================================
set -uo pipefail

HEALTH_URL="${HEALTH_URL:-http://localhost:8000/health}"
COMPOSE_DIR="${COMPOSE_DIR:-/opt/stockcast}"
COMPOSE_FILES="${COMPOSE_FILES:-}"      # 예: "-f docker-compose.yml -f docker-compose.rds.yml"
STATE_DIR="${STATE_DIR:-/var/lib/stockcast}"
LOG_FILE="${LOG_FILE:-/var/log/stockcast-watchdog.log}"
DOCKER="${DOCKER:-docker}"

TRIES="${TRIES:-3}"                     # 판단 전 재시도 횟수
TIMEOUT="${TIMEOUT:-5}"                 # 요청 하나당 제한시간(초)
MAX_ACTIONS_PER_HOUR="${MAX_ACTIONS_PER_HOUR:-4}"

FAIL_FILE="$STATE_DIR/consecutive_failures"
ACTION_LOG="$STATE_DIR/recent_actions"

mkdir -p "$STATE_DIR" 2>/dev/null || true
touch "$FAIL_FILE" "$ACTION_LOG" 2>/dev/null || true

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE" >&2; }

# 최근 한 시간 안에 조치를 몇 번 했는지 센다.
# 고장이 안 풀리는데 2분마다 재시작하면 상황만 나빠진다.
recent_action_count() {
  local cutoff now
  now=$(date +%s); cutoff=$(( now - 3600 ))
  awk -v c="$cutoff" '$1 > c' "$ACTION_LOG" 2>/dev/null | wc -l | tr -d ' '
}

record_action() {
  local now; now=$(date +%s)
  echo "$now $1" >> "$ACTION_LOG"
  # 파일이 무한정 자라지 않게 최근 한 시간치만 남긴다.
  awk -v c="$(( now - 3600 ))" '$1 > c' "$ACTION_LOG" > "$ACTION_LOG.tmp" 2>/dev/null \
    && mv "$ACTION_LOG.tmp" "$ACTION_LOG"
}

compose() { ( cd "$COMPOSE_DIR" && $DOCKER compose $COMPOSE_FILES "$@" ); }

# ── 헬스체크 ────────────────────────────────────────────────
healthy=0
for i in $(seq 1 "$TRIES"); do
  if curl -fsS --max-time "$TIMEOUT" "$HEALTH_URL" >/dev/null 2>&1; then
    healthy=1; break
  fi
  [ "$i" -lt "$TRIES" ] && sleep 3
done

if [ "$healthy" -eq 1 ]; then
  prev=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
  [ "${prev:-0}" -gt 0 ] && log "정상 복귀 (직전 연속 실패 ${prev}회)"
  echo 0 > "$FAIL_FILE"
  exit 0
fi

# ── 실패 처리 ───────────────────────────────────────────────
fails=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
case "$fails" in ''|*[!0-9]*) fails=0 ;; esac
fails=$(( fails + 1 ))
echo "$fails" > "$FAIL_FILE"
log "헬스체크 실패 ${fails}회 연속 ($HEALTH_URL)"

acted=$(recent_action_count)
if [ "$acted" -ge "$MAX_ACTIONS_PER_HOUR" ]; then
  log "최근 1시간 조치 ${acted}회로 상한(${MAX_ACTIONS_PER_HOUR})에 걸렸다. 자동 복구를 멈추고 사람 확인을 기다린다."
  exit 1
fi

if [ "$fails" -eq 1 ]; then
  log "1단계 — backend 컨테이너만 재시작"
  record_action restart-backend
  compose restart backend >>"$LOG_FILE" 2>&1 && log "backend 재시작 완료" || log "backend 재시작 실패"
elif [ "$fails" -eq 2 ]; then
  log "2단계 — compose 전체 재기동"
  record_action recreate-stack
  compose up -d --force-recreate >>"$LOG_FILE" 2>&1 && log "전체 재기동 완료" || log "전체 재기동 실패"
else
  log "3회 이상 연속 실패. 자동 조치를 중단한다. 'docker compose logs backend' 로 직접 확인할 것."
fi
exit 1
