# ============================================================
# Terraform 상태를 둘 곳을 만든다. 딱 한 번만 돌리면 된다.
#
# 지금은 상태가 로컬 파일 하나(infra/terraform/terraform.tfstate)다. 두 가지가 걸린다.
#
#   1) 잠금이 없다. 두 곳에서 동시에 apply 하면 상태가 깨진다
#   2) 날아가면 끝이다. 상태를 잃으면 terraform 이 기존 리소스를 모르고,
#      이미 있는 걸 또 만들려고 든다
#
# 실제로 이번에 상태와 AWS 가 어긋난 걸 겪었다. 상태에는 EC2·EIP·SG 가 있는데
# AWS 에는 없었다. 원격 상태가 그걸 막아주진 않지만, 버전 관리를 켜 두면
# 어느 시점으로든 되돌릴 수 있다.
#
# 이 디렉터리는 상태를 로컬에 둔다. 상태를 담을 곳을 만드는 코드라
# 자기 자신을 거기 둘 수는 없다.
#
# 비용: S3 는 몇 KB 파일 몇 개라 사실상 0원.
#       DynamoDB 는 온디맨드라 apply 할 때만 몇 건 읽고 쓴다. 월 몇 센트.
#
#   cd infra/terraform-bootstrap && terraform init && terraform apply
# ============================================================

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "ap-northeast-2"
}

variable "project" {
  type    = string
  default = "stockcast"
}

data "aws_caller_identity" "current" {}

# 버킷 이름은 전 세계에서 유일해야 한다. 계정 ID를 붙여 겹치지 않게 한다.
locals {
  bucket_name = "${var.project}-tfstate-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.bucket_name

  # 실수로 지우는 걸 막는다. 지우려면 이 줄을 먼저 false 로 바꾸고 apply 해야 한다.
  lifecycle {
    prevent_destroy = true
  }

  tags = { Project = var.project }
}

# 버전 관리. 상태를 잘못 덮어써도 이전 버전으로 되돌릴 수 있다.
# 원격 상태를 쓰는 이유의 절반이 이것이다.
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

# 상태 파일에는 DB 비밀번호가 평문으로 들어간다. 반드시 암호화한다.
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # AWS 관리 키. 추가 비용 없다.
    }
  }
}

# 공개 접근을 완전히 막는다. 기본값이 바뀌어도 여기서 한 번 더 잠근다.
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# 옛 버전이 무한정 쌓이지 않게 한다. 상태 파일은 작지만 apply 마다 버전이 생긴다.
resource "aws_s3_bucket_lifecycle_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}

# 동시 apply 를 막는 잠금 테이블.
# 온디맨드라 쓴 만큼만 낸다. apply 한 번에 몇 건이라 사실상 0원.
resource "aws_dynamodb_table" "tflock" {
  name         = "${var.project}-tflock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID" # terraform 이 이 이름을 요구한다

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = { Project = var.project }
}

output "backend_config" {
  description = "infra/terraform/backend.tf 에 넣을 내용"
  value       = <<-EOT

    terraform {
      backend "s3" {
        bucket         = "${aws_s3_bucket.tfstate.id}"
        key            = "${var.project}/terraform.tfstate"
        region         = "${var.aws_region}"
        dynamodb_table = "${aws_dynamodb_table.tflock.name}"
        encrypt        = true
      }
    }
  EOT
}
