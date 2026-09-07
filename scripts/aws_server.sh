#!/usr/bin/env bash
# ============================================================
# 서버를 필요할 때만 켠다. 프리티어가 끝난 뒤 비용을 줄이는 가장 큰 수단이다.
#
#   ./scripts/aws_server.sh status   지금 상태와 이번 달 비용
#   ./scripts/aws_server.sh start    EC2(+RDS) 시작하고 DuckDNS 주소 갱신
#   ./scripts/aws_server.sh stop     EC2(+RDS) 정지
#   ./scripts/aws_server.sh cost     이번 달 서비스별 비용
#
# 정지하면 EC2 시간요금과 공인 IPv4 요금이 안 나간다. EBS 스토리지만 남는다.
# RDS도 정지되지만 AWS가 7일 뒤 자동으로 다시 켠다. 오래 안 쓸 거면 스냅샷을
# 뜨고 지우는 편이 낫다.
# ============================================================
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-2}"
PROJECT="${PROJECT:-stockcast}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.env" ] && set -a && . "$ROOT/.env" 2>/dev/null && set +a || true

aws_ec2() { aws ec2 --region "$REGION" "$@"; }

instance_id() {
  aws_ec2 describe-instances \
    --filters "Name=tag:Project,Values=$PROJECT" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[].Instances[0].InstanceId' --output text 2>/dev/null | head -1
}

db_id() {
  aws rds --region "$REGION" describe-db-instances \
    --query "DBInstances[?DBInstanceIdentifier=='${PROJECT}-db'].DBInstanceIdentifier" \
    --output text 2>/dev/null | head -1
}

# EIP 없이 운영하면 켤 때마다 공인 IP가 바뀐다. DuckDNS 가 그걸 따라가게 한다.
# EIP를 붙여 두면 정지 중에도 유휴 주소 요금이 나가므로, 자주 껐다 켤 거면 이쪽이 싸다.
update_duckdns() {
  local ip="$1"
  local domain="${DUCKDNS_DOMAIN:-}" token="${DUCKDNS_TOKEN:-}"
  if [ -z "$domain" ] || [ -z "$token" ]; then
    echo "  DuckDNS 설정이 없다(.env 의 DUCKDNS_DOMAIN·DUCKDNS_TOKEN). 주소 갱신은 건너뛴다."
    return 0
  fi
  local r
  r=$(curl -sS "https://www.duckdns.org/update?domains=${domain}&token=${token}&ip=${ip}")
  echo "  DuckDNS ${domain} → ${ip} : ${r}"
}

case "${1:-status}" in

status)
  IID=$(instance_id)
  if [ -z "$IID" ] || [ "$IID" = "None" ]; then
    echo "EC2   없음 (아직 안 만들었거나 종료됨)"
  else
    aws_ec2 describe-instances --instance-ids "$IID" \
      --query 'Reservations[].Instances[].[InstanceId,State.Name,InstanceType,PublicIpAddress]' \
      --output text | awk '{printf "EC2   %s  %s  %s  %s\n",$1,$2,$3,($4=="None"?"(공인IP 없음)":$4)}'
  fi
  DID=$(db_id)
  if [ -z "$DID" ] || [ "$DID" = "None" ]; then
    echo "RDS   없음 (use_rds = false)"
  else
    aws rds --region "$REGION" describe-db-instances --db-instance-identifier "$DID" \
      --query 'DBInstances[].[DBInstanceIdentifier,DBInstanceStatus,DBInstanceClass]' --output text \
      | awk '{printf "RDS   %s  %s  %s\n",$1,$2,$3}'
  fi
  echo; "$0" cost
  ;;

start)
  IID=$(instance_id)
  [ -n "$IID" ] && [ "$IID" != "None" ] || { echo "EC2가 없다. terraform apply 부터 할 것." >&2; exit 1; }
  DID=$(db_id)
  if [ -n "$DID" ] && [ "$DID" != "None" ]; then
    # DB가 먼저 떠 있어야 앱이 붙는다.
    echo "RDS 시작..."
    aws rds --region "$REGION" start-db-instance --db-instance-identifier "$DID" >/dev/null 2>&1 || true
    aws rds --region "$REGION" wait db-instance-available --db-instance-identifier "$DID" || true
    echo "  RDS 준비됨"
  fi
  echo "EC2 시작..."
  aws_ec2 start-instances --instance-ids "$IID" >/dev/null
  aws_ec2 wait instance-running --instance-ids "$IID"
  IP=$(aws_ec2 describe-instances --instance-ids "$IID" \
        --query 'Reservations[].Instances[].PublicIpAddress' --output text)
  echo "  EC2 실행중 — $IP"
  update_duckdns "$IP"
  echo "앱이 뜰 때까지 대기..."
  for i in $(seq 1 40); do
    curl -fsS --max-time 3 "http://$IP:8000/health" >/dev/null 2>&1 && { echo "  준비됨 (${i}회 시도)"; exit 0; }
    sleep 10
  done
  echo "  400초 안에 안 떴다. ssh 로 'systemctl status stockcast' 를 볼 것." >&2
  exit 1
  ;;

stop)
  IID=$(instance_id)
  if [ -n "$IID" ] && [ "$IID" != "None" ]; then
    aws_ec2 stop-instances --instance-ids "$IID" >/dev/null && echo "EC2 정지 요청 — $IID"
  fi
  DID=$(db_id)
  if [ -n "$DID" ] && [ "$DID" != "None" ]; then
    aws rds --region "$REGION" stop-db-instance --db-instance-identifier "$DID" >/dev/null 2>&1 \
      && echo "RDS 정지 요청 — $DID (7일 뒤 AWS가 자동으로 다시 켠다)"
  fi
  echo "정지 중에도 EBS 스토리지 요금은 계속 나간다."
  ;;

cost)
  S=$(date -u +%Y-%m-01); E=$(date -u +%Y-%m-%d)
  [ "$S" = "$E" ] && { echo "이번 달 비용: 달이 막 바뀌어 집계할 구간이 없다."; exit 0; }
  echo "이번 달 비용 ($S ~ $E, USD)"
  aws ce get-cost-and-usage --region us-east-1 \
    --time-period "Start=$S,End=$E" --granularity MONTHLY --metrics UnblendedCost \
    --group-by Type=DIMENSION,Key=SERVICE --output json 2>/dev/null \
  | python3 -c "
import sys,json
try: d=json.load(sys.stdin)
except Exception: print('  Cost Explorer 조회 실패 (권한이나 활성화 여부 확인)'); sys.exit()
tot=0.0
rows=[]
for g in d['ResultsByTime'][0]['Groups']:
    a=float(g['Metrics']['UnblendedCost']['Amount'])
    if a < 0.01: continue
    rows.append((a,g['Keys'][0])); tot+=a
for a,k in sorted(rows, reverse=True):
    print(f'  {k[:44]:44} \${a:7.2f}')
print(f'  {\"합계\":40} \${tot:7.2f}')
" || echo "  조회 실패"
  ;;

*) sed -n '3,12p' "$0"; exit 2 ;;
esac
