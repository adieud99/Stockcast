# ============================================================
# StockCast 인프라 — EC2(t3.small) + RDS. 앱은 Docker로 띄운다
#   비용 최소화(프리티어 EC2 1대) + 로컬과 동일한 docker compose 실행
#   RDS 분리는 운영 확장 과제(docs/10-deployment.md 참고)
# ============================================================

# 기본 VPC / 서브넷 사용 (별도 네트워크 구성 없이 프리티어 범위)
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# 인스턴스 타입에서 CPU 아키텍처를 뽑는다.
# t4g / m7g 처럼 세대 숫자 뒤에 g 가 붙으면 Graviton(ARM)이다.
# 같은 성능에 20% 싸고, 쓰는 이미지(odoo·postgres·caddy·python)가 전부
# arm64 를 지원하는 걸 확인하고 기본값을 t4g.micro 로 뒀다.
locals {
  cpu_arch = can(regex("^[a-z]+[0-9]+g", var.instance_type)) ? "arm64" : "x86_64"
}

# 최신 Amazon Linux 2023 AMI (아키텍처에 맞춰 고른다)
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-${local.cpu_arch}"]
  }
  filter {
    name   = "architecture"
    values = [local.cpu_arch]
  }
}

# 보안 그룹: SSH(내 IP만), HTTP 8000(데모용 전체 허용)
resource "aws_security_group" "app" {
  name        = "${var.project}-sg"
  description = "StockCast app security group"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip]
  }

  # 8000 을 전 세계에 열면 Caddy 가 443 에 걸어 둔 HTTPS 를 우회할 수 있다.
  # http://<공인IP>:8000 으로 그냥 붙어지고, 그 트래픽은 암호화가 안 된다.
  # 인증서를 붙여 놓고 옆문을 열어 두는 셈이라, 기본은 내 IP 로만 연다.
  # Caddy 는 같은 호스트 안에서 붙으므로 이 규칙과 무관하게 동작한다.
  ingress {
    description = "App FastAPI (default: my IP only; set open_app_port to publish)"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.open_app_port ? ["0.0.0.0/0"] : [var.my_ip]
  }

  # Odoo 는 로그인 폼이 있다. 평문으로 열어 두면 비밀번호가 그대로 지나간다.
  # 데모로 보여줘야 하면 그때만 open_odoo_port 를 켠다.
  ingress {
    description = "Odoo ERP web (default: my IP only)"
    from_port   = 8069
    to_port     = 8069
    protocol    = "tcp"
    cidr_blocks = var.open_odoo_port ? ["0.0.0.0/0"] : [var.my_ip]
  }

  ingress {
    description = "HTTP (Caddy / Lets Encrypt)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTPS (Caddy)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
}

# EC2 인스턴스 (Docker + 앱 자동 기동)
resource "aws_instance" "app" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  key_name                    = var.key_pair_name
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.app.id]
  associate_public_ip_address = true

  # SSM 을 쓰면 역할을 붙인다. 키를 인스턴스에 심지 않아도 파라미터를 읽을 수 있다.
  iam_instance_profile = var.use_ssm ? aws_iam_instance_profile.app[0].name : null

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url        = var.repo_url
    db_password     = var.use_ssm ? "" : var.db_password
    gemini_api_key  = var.use_ssm ? "" : var.gemini_api_key
    kma_api_key     = var.use_ssm ? "" : var.kma_api_key
    holiday_api_key = var.use_ssm ? "" : var.holiday_api_key

    stockcast_domain = var.stockcast_domain
    db_major_version = var.db_engine_version
    swap_mb          = var.swap_mb
    use_ssm          = var.use_ssm
    ssm_prefix       = local.ssm_prefix
    aws_region       = var.aws_region

    # use_rds = false 면 빈 문자열이 들어간다. user_data 는 이 값이 비었는지로
    # RDS를 쓸지 말지를 판단한다.
    rds_database_url = var.use_rds ? format(
      "postgresql+psycopg://erp:%s@%s/erp_nfc", local.effective_db_password, aws_db_instance.app[0].endpoint
    ) : ""
    rds_database_url_psycopg = var.use_rds ? format(
      "host=%s port=%d dbname=erp_nfc user=erp password=%s",
      aws_db_instance.app[0].address, aws_db_instance.app[0].port, local.effective_db_password
    ) : ""
  })

  root_block_device {
    volume_size = 20 # 프리티어 30GB 이내
    volume_type = "gp3"
  }

  tags = { Project = var.project, Name = "${var.project}-app" }
}

# 고정 공인 IP(Elastic IP). 기본은 안 만든다.
#
# EIP 를 붙이면 껐다 켜도 주소가 그대로다. 대신 인스턴스를 정지해 둔 동안에도
# 시간당 요금이 계속 나간다(IdleAddress, InUseAddress 와 같은 $0.005/시간).
#
# 안 붙이면 EC2 가 켜질 때마다 주소를 새로 받는다. 정지 중에는 주소를 반납하므로
# 그만큼 요금이 0이 된다. 주소가 바뀌는 건 DuckDNS 가 따라가면 된다
# (scripts/aws_server.sh start 가 켠 뒤 갱신한다).
#
# 어차피 접속은 도메인으로 하고 IP 를 직접 치지 않으므로, 껐다 켤 거면 안 붙이는 게 싸다.
# 24시간 돌릴 거면 요금이 같으니 use_eip = true 로 두는 편이 신경 쓸 게 없다.
resource "aws_eip" "app" {
  count    = var.use_eip ? 1 : 0
  domain   = "vpc"
  instance = aws_instance.app.id
  tags     = { Project = var.project }
}
