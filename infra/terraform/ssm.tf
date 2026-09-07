# ============================================================
# 비밀값을 user_data 밖으로 뺀다.
#
# 지금까지는 user_data 가 .env 를 평문으로 만들었다. 문제는 이 값이
# 인스턴스 메타데이터로 그대로 읽힌다는 것이다.
#
#   curl http://169.254.169.254/latest/user-data
#
# EC2 안에서 도는 아무 프로세스나 이걸 호출할 수 있다. 앱이 뚫리면
# API 키 4개와 DB 비밀번호가 같이 넘어간다.
#
# SSM Parameter Store 로 옮기면 user_data 에는 "어느 파라미터를 읽어라"만 남는다.
# 값을 꺼내려면 IAM 권한이 있어야 하고, 누가 언제 꺼냈는지 CloudTrail 에 남는다.
#
# 파라미터 자체는 terraform 이 만들지 않는다. 만들면 값이 tfstate 에 들어가서
# 옮긴 의미가 절반으로 준다. scripts/put_secrets.sh 로 먼저 넣어 두고
# 여기서는 읽기만 한다.
#
# 표준 파라미터(4KB 이하)는 무료다. SecureString 도 AWS 관리 키를 쓰면 추가 비용이 없다.
# ============================================================

locals {
  ssm_prefix = "/${var.project}"

  # RDS 와 접속 URL 이 같은 비밀번호를 봐야 한다. 한 곳에서 정한다.
  effective_db_password = var.use_ssm ? data.aws_ssm_parameter.db_password[0].value : var.db_password
}

# EC2 가 파라미터를 읽을 수 있게 하는 역할.
# 키를 인스턴스에 심는 대신 역할을 붙인다. 자격증명이 자동으로 돌아간다.
resource "aws_iam_role" "app" {
  count = var.use_ssm ? 1 : 0
  name  = "${var.project}-ec2-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Project = var.project }
}

# 필요한 것만 준다. /stockcast/ 아래만 읽을 수 있고 쓰기는 못 한다.
# ssm:* 를 주면 다른 프로젝트 비밀값까지 읽힌다.
resource "aws_iam_role_policy" "ssm_read" {
  count = var.use_ssm ? 1 : 0
  name  = "${var.project}-ssm-read"
  role  = aws_iam_role.app[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_prefix}/*"
      },
      {
        # SecureString 을 풀려면 KMS 복호화가 필요하다.
        # AWS 관리 키(alias/aws/ssm)로 제한해서, 다른 키로는 못 풀게 한다.
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_instance_profile" "app" {
  count = var.use_ssm ? 1 : 0
  name  = "${var.project}-ec2-profile"
  role  = aws_iam_role.app[0].name
}

data "aws_caller_identity" "current" {}

# RDS 비밀번호는 미리 넣어 둔 파라미터에서 읽는다.
# 이렇게 해도 값은 tfstate 에 남는다(데이터 소스는 상태에 저장된다).
# 완전히 빼려면 RDS 의 manage_master_user_password 를 쓰면 되는데,
# 그건 Secrets Manager 를 쓰므로 월 $0.40 이 붙는다. 지금은 안 켰다.
data "aws_ssm_parameter" "db_password" {
  count           = var.use_ssm ? 1 : 0
  name            = "${local.ssm_prefix}/db_password"
  with_decryption = true
}
