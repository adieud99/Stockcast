variable "aws_region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2" # 서울
}

variable "project" {
  description = "리소스 이름 접두어"
  type        = string
  default     = "stockcast"
}

variable "instance_type" {
  description = "EC2 인스턴스 타입. t4g 계열이면 AMI 를 자동으로 arm64 로 고른다"
  type        = string
  # 메모리는 2GB를 유지한다. 1GB(micro)로는 Odoo 가 안 떴던 기록이 있다.
  # 실측으로는 backend 174MB + odoo 196MB + DB 두 개 60MB = 약 430MB 라 1GB 에도
  # 들어가지만, Odoo 모듈 설치와 이미지 빌드 때 순간적으로 크게 튄다.
  # 아키텍처만 ARM 으로 바꿔서 같은 2GB 를 월 $18.98 -> $15.18 로 줄인다.
  default = "t4g.small"
}

variable "key_pair_name" {
  description = "SSH 접속용 기존 EC2 Key Pair 이름 (콘솔에서 미리 생성)"
  type        = string
}

variable "my_ip" {
  description = "SSH(22) 허용할 내 공인 IP (예: 1.2.3.4/32)"
  type        = string
}

variable "swap_mb" {
  description = "스왑 파일 크기(MB). Odoo 모듈 설치·pip 빌드 때 메모리가 튀어서 필요하다. 0이면 안 만든다"
  type        = number
  default     = 2048
}

variable "open_app_port" {
  description = "8000 을 전 세계에 열지 여부. Caddy(443) 를 쓰면 열 이유가 없다. 열면 HTTPS 우회가 된다"
  type        = bool
  default     = false
}

variable "open_odoo_port" {
  description = "8069(Odoo) 를 전 세계에 열지 여부. 평문 로그인이라 기본은 닫는다"
  type        = bool
  default     = false
}

variable "repo_url" {
  description = "EC2가 clone할 GitHub 저장소 URL (public 또는 토큰 포함)"
  type        = string
}

variable "db_password" {
  description = "PostgreSQL 비밀번호. use_ssm = true 면 비워 두고 SSM 에서 읽는다"
  type        = string
  sensitive   = true
  default     = ""

  # 이 값이 그대로 접속 URL 에 들어간다.
  #   postgresql+psycopg://erp:<비밀번호>@호스트:5432/erp_nfc
  # @ 나 / 같은 문자가 섞이면 URL 이 엉뚱하게 잘려서, 인증 실패가 아니라
  # "호스트를 못 찾겠다" 같은 엉뚱한 에러로 나타난다. 원인 찾기가 오래 걸린다.
  # 빈 값은 통과시킨다. use_ssm 을 쓰면 여기 값이 없는 게 정상이다.
  validation {
    condition     = var.db_password == "" || can(regex("^[A-Za-z0-9!$*_.~-]+$", var.db_password))
    error_message = "db_password 에는 영문·숫자와 ! $ * _ . ~ - 만 쓸 것. @ / : ? # % [ ] 공백은 접속 URL 을 깨뜨린다."
  }

  # RDS 는 8자 미만을 거부한다. apply 를 한참 돌린 뒤에 실패하지 않도록 먼저 막는다.
  validation {
    condition     = var.db_password == "" || length(var.db_password) >= 8
    error_message = "db_password 는 8자 이상이어야 한다 (RDS 요구사항)."
  }
}

variable "gemini_api_key" {
  description = "Gemini API 키"
  type        = string
  sensitive   = true
  default     = ""
}

variable "kma_api_key" {
  description = "기상청 API 키"
  type        = string
  sensitive   = true
  default     = ""
}

variable "holiday_api_key" {
  description = "공휴일 API 키"
  type        = string
  sensitive   = true
  default     = ""
}

# ── RDS 전환 (3단계) ─────────────────────────────────────────
# false 로 두면 RDS 관련 리소스를 하나도 만들지 않는다. 기존 구성 그대로.

variable "use_rds" {
  description = "분석계 DB를 RDS로 분리할지 여부. false면 EC2 안 Postgres 컨테이너를 계속 쓴다"
  type        = bool
  default     = false
}

variable "db_instance_class" {
  description = "RDS 인스턴스 클래스 (프리티어: db.t4g.micro / db.t3.micro)"
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "PostgreSQL 메이저 버전. 로컬 컨테이너(postgres:16)와 맞춘다"
  type        = string
  default     = "16"
}

variable "db_allocated_storage" {
  description = "RDS 스토리지 GB. 프리티어 한도가 20GB다"
  type        = number
  default     = 20
}

variable "db_storage_type" {
  description = "스토리지 타입. 프리티어 20GB는 gp2 기준이라 기본을 gp2로 둔다"
  type        = string
  default     = "gp2"
}

variable "db_backup_retention" {
  description = "자동 백업 보관일수. 0이면 백업·시점복구가 아예 안 된다. 프리티어 백업 한도는 20GB"
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "실수로 DB를 지우는 걸 막는다. 지울 때는 false로 바꾸고 apply 먼저 해야 한다"
  type        = bool
  default     = true
}

variable "db_skip_final_snapshot" {
  description = "삭제 시 마지막 스냅샷을 건너뛸지. 과제 정리용이면 true, 실제 운영이면 false"
  type        = bool
  default     = false
}

# ── 서버 자동 복구 (3단계) ───────────────────────────────────

variable "enable_autorecovery" {
  description = "EC2 상태검사 실패 시 자동 복구/재부팅 알람을 만들지 여부"
  type        = bool
  default     = true
}

variable "enable_disk_alarm" {
  description = "루트 볼륨 사용률 알람. CloudWatch Agent 설치가 따로 필요하고 사용자 지표 요금(월 $0.30)이 붙는다"
  type        = bool
  default     = false
}

variable "alarm_email" {
  description = "알람 수신 메일. 비워 두면 SNS 주제와 디스크 알람을 만들지 않는다"
  type        = string
  default     = ""
}

variable "stockcast_domain" {
  description = "Caddy 가 인증서를 받을 도메인 (DuckDNS). 비우면 HTTPS 없이 8000 포트로만 뜬다"
  type        = string
  default     = ""
}

variable "monthly_budget_usd" {
  description = "월 예산(USD). 80% 도달과 초과 예상 시 메일이 온다. 0이면 예산을 만들지 않는다"
  type        = number
  default     = 20
}

variable "use_ssm" {
  description = "비밀값을 SSM Parameter Store 에서 읽을지 여부. 켜기 전에 scripts/put_secrets.sh 로 값을 먼저 넣어야 한다"
  type        = bool
  default     = false
}
