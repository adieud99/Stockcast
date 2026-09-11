#!/usr/bin/env bash
# ============================================================
# .env 의 비밀값을 SSM Parameter Store 에 넣는다.
#
#   ./scripts/put_secrets.sh          무엇이 올라갈지 보여주기만 한다
#   ./scripts/put_secrets.sh --apply  실제로 넣는다
#   ./scripts/put_secrets.sh --list   지금 들어 있는 것 확인 (값은 안 보여준다)
#
# terraform 이 이 파라미터를 만들지 않는 이유가 있다. terraform 이 만들면
# 값이 tfstate 에 평문으로 남아서, user_data 에서 뺀 의미가 절반으로 준다.
# 값은 여기서 넣고 terraform 은 읽기만 한다.
#
# 표준 파라미터(4KB 이하)는 무료다. SecureString 도 AWS 관리 키(alias/aws/ssm)를
# 쓰면 추가 비용이 없다.
# ============================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REGION="${AWS_REGION:-ap-northeast-2}"
PROJECT="${PROJECT:-stockcast}"
PREFIX="/${PROJECT}"
MODE="${1:-dry}"

command -v aws >/dev/null || { echo "aws CLI 가 필요하다." >&2; exit 3; }

# .env 에서 읽어 SSM 에 넣을 것들. user_data 가 부팅할 때 같은 이름으로 꺼내 간다.
KEYS="POSTGRES_PASSWORD:db_password
GEMINI_API_KEY:gemini_api_key
KMA_API_KEY:kma_api_key
HOLIDAY_API_KEY:holiday_api_key
NARA_API_KEY:nara_api_key
PPS_API_KEY:pps_api_key
ODOO_PASSWORD:odoo_password
AUTH_SECRET:auth_secret
AUTH_ADMIN_PASSWORD:auth_admin_password
AUTH_VIEWER_PASSWORD:auth_viewer_password"

if [ "$MODE" = "--list" ]; then
  echo "현재 ${PREFIX} 아래 파라미터 (값은 표시하지 않는다)"
  aws ssm get-parameters-by-path --region "$REGION" --path "$PREFIX" \
    --query 'Parameters[].[Name,Type,LastModifiedDate]' --output text 2>/dev/null \
    | sed 's/^/  /' || echo "  없음"
  exit 0
fi

[ -f "$ROOT/.env" ] || { echo ".env 가 없다: $ROOT/.env" >&2; exit 2; }

echo "리전 $REGION · 접두어 $PREFIX"
[ "$MODE" = "--apply" ] || echo "(미리보기 — 실제로 넣으려면 --apply)"
echo

COUNT=0
while IFS= read -r line; do
  ENVKEY="${line%%:*}"; SSMKEY="${line##*:}"
  VAL=$(grep -E "^${ENVKEY}=" "$ROOT/.env" | head -1 | cut -d= -f2- | sed 's/[[:space:]]*$//')

  if [ -z "$VAL" ]; then
    printf '  %-22s -> %-24s 건너뜀 (.env 에 값이 없다)\n' "$ENVKEY" "$PREFIX/$SSMKEY"
    continue
  fi

  # 값은 절대 찍지 않는다. 길이와 앞 두 글자만 보여준다.
  MASK="$(printf '%s' "$VAL" | cut -c1-2)$(printf '%*s' $(( ${#VAL} - 2 )) '' | tr ' ' '*')"
  printf '  %-22s -> %-24s %s\n' "$ENVKEY" "$PREFIX/$SSMKEY" "$MASK"

  if [ "$MODE" = "--apply" ]; then
    aws ssm put-parameter --region "$REGION" \
      --name "$PREFIX/$SSMKEY" --type SecureString --value "$VAL" --overwrite >/dev/null
    COUNT=$((COUNT+1))
  fi
done <<< "$KEYS"

echo
if [ "$MODE" = "--apply" ]; then
  echo "$COUNT 개 저장했다. 다음으로 할 일:"
  echo "  1) terraform.tfvars 에 use_ssm = true"
  echo "  2) tfvars 에서 db_password·gemini_api_key·kma_api_key·holiday_api_key 를 지운다"
  echo "     (지우면 tfstate 에도 안 남는다. db_password 만 SSM 데이터소스를 거쳐 남는다)"
  echo "  3) terraform apply"
else
  echo "실제로 넣으려면 --apply 를 붙인다."
fi
