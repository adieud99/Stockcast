output "public_ip" {
  description = "EC2 공인 IP"
  value       = aws_eip.app.public_ip
}

output "app_url" {
  description = "앱 접속 주소"
  value       = "http://${aws_eip.app.public_ip}:8000"
}

output "dashboard_url" {
  description = "KPI 대시보드"
  value       = "http://${aws_eip.app.public_ip}:8000/dashboard"
}

output "ssh_command" {
  description = "SSH 접속 명령"
  value       = "ssh -i <키파일>.pem ec2-user@${aws_eip.app.public_ip}"
}

# ── RDS (use_rds = true 일 때만 값이 나온다) ──────────────────

output "rds_endpoint" {
  description = "RDS 접속 주소 host:port"
  value       = var.use_rds ? aws_db_instance.app[0].endpoint : "(use_rds = false)"
}

output "rds_database_url" {
  description = ".env 의 RDS_DATABASE_URL 에 넣을 값. 비밀번호가 들어 있어 가려서 출력된다"
  value = var.use_rds ? format(
    "postgresql+psycopg://erp:%s@%s/erp_nfc",
    local.effective_db_password,
    aws_db_instance.app[0].endpoint
  ) : "(use_rds = false)"
  sensitive = true
}

output "rds_database_url_psycopg" {
  description = ".env 의 RDS_DATABASE_URL_PSYCOPG 에 넣을 값"
  value = var.use_rds ? format(
    "host=%s port=%d dbname=erp_nfc user=erp password=%s",
    aws_db_instance.app[0].address,
    aws_db_instance.app[0].port,
    var.db_password
  ) : "(use_rds = false)"
  sensitive = true
}
