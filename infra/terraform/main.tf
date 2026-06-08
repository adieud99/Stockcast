# ============================================================
# StockCast 인프라 — 단일 EC2(t3.micro)에 Docker로 통합 운영
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

# 최신 Amazon Linux 2023 AMI
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
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

  ingress {
    description = "App FastAPI"
    from_port   = 8000
    to_port     = 8000
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

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    repo_url        = var.repo_url
    db_password     = var.db_password
    gemini_api_key  = var.gemini_api_key
    kma_api_key     = var.kma_api_key
    holiday_api_key = var.holiday_api_key
  })

  root_block_device {
    volume_size = 20 # 프리티어 30GB 이내
    volume_type = "gp3"
  }

  tags = { Project = var.project, Name = "${var.project}-app" }
}
