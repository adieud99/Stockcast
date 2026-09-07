# ============================================================
# 분석계 DB를 EC2 안 Postgres 컨테이너에서 RDS로 분리한다.
#
# use_rds = false 면 이 파일은 아무것도 만들지 않는다. 기존 구성 그대로다.
# true 로 바꾸고 apply 하면 RDS가 생기고, 그때 데이터를 옮긴 뒤
# docker-compose.rds.yml 로 앱을 다시 띄우면 전환이 끝난다.
#
# EC2 안에서 Postgres를 돌리던 걸 굳이 빼는 이유는 두 가지다.
#   1) t3.micro 메모리가 1GB뿐인데 backend·postgres·odoo·odoo_db·caddy 가 다 올라간다
#   2) 인스턴스가 날아가면 데이터도 같이 날아간다. 백업이 EBS 스냅샷뿐이다
# ============================================================

# RDS는 서브넷 그룹이 있어야 만들어진다. 기본 VPC의 서브넷을 그대로 쓴다.
resource "aws_db_subnet_group" "app" {
  count       = var.use_rds ? 1 : 0
  name        = "${var.project}-db-subnet"
  subnet_ids  = data.aws_subnets.default.ids
  description = "StockCast RDS 서브넷 그룹 (기본 VPC)"

  tags = { Project = var.project }
}

# DB 보안그룹 — CIDR 이 아니라 앱 EC2의 보안그룹에서만 5432를 연다.
# 0.0.0.0/0 이나 내 IP로 열면 DB가 인터넷에 노출된다. SG 참조로 묶으면
# EC2 IP가 바뀌어도 규칙을 고칠 필요가 없다.
resource "aws_security_group" "db" {
  count       = var.use_rds ? 1 : 0
  name        = "${var.project}-db-sg"
  description = "StockCast RDS - 앱 EC2에서만 5432 허용"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "PostgreSQL from app EC2 only"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    description = "All outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
}

resource "aws_db_instance" "app" {
  count      = var.use_rds ? 1 : 0
  identifier = "${var.project}-db"

  engine         = "postgres"
  engine_version = var.db_engine_version
  instance_class = var.db_instance_class

  allocated_storage = var.db_allocated_storage
  storage_type      = var.db_storage_type
  storage_encrypted = true # AWS 관리 키(aws/rds). 추가 비용 없다.

  db_name  = "erp_nfc"
  username = "erp"
  # SSM 을 쓰면 거기서 읽는다. 안 쓰면 tfvars 값을 그대로 쓴다.
  password = var.use_ssm ? data.aws_ssm_parameter.db_password[0].value : var.db_password
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.app[0].name
  vpc_security_group_ids = [aws_security_group.db[0].id]

  # 공인 주소를 주지 않는다. 접근은 같은 VPC의 EC2를 통해서만.
  publicly_accessible = false

  # 자동 백업. 0으로 두면 백업이 아예 안 돌고 시점 복구도 못 한다.
  # 시간은 UTC 기준이라 17:00 = 한국시간 새벽 2시다.
  backup_retention_period    = var.db_backup_retention
  backup_window              = "17:00-17:30"
  maintenance_window         = "mon:18:00-mon:18:30"
  auto_minor_version_upgrade = true

  # 프리티어는 Single-AZ만 해당된다. Multi-AZ 를 켜면 요금이 두 배가 된다.
  multi_az = false

  # Performance Insights 는 인스턴스 클래스에 따라 과금될 수 있어 꺼 둔다.
  performance_insights_enabled = false

  # 스토리지 자동 확장은 일부러 끈다(max_allocated_storage 미지정).
  # 켜두면 조용히 20GB를 넘어 프리티어 밖으로 나간다.

  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${var.project}-db-final"

  # 변경을 즉시 반영하지 않고 유지보수 창에서 처리한다. 갑작스런 재시작을 막는다.
  apply_immediately = false

  tags = { Project = var.project, Name = "${var.project}-db" }
}
