output "public_ip" {
  description = "EC2 공인 IP"
  value       = aws_instance.app.public_ip
}

output "app_url" {
  description = "앱 접속 주소"
  value       = "http://${aws_instance.app.public_ip}:8000"
}

output "dashboard_url" {
  description = "KPI 대시보드"
  value       = "http://${aws_instance.app.public_ip}:8000/dashboard"
}

output "ssh_command" {
  description = "SSH 접속 명령"
  value       = "ssh -i <키파일>.pem ec2-user@${aws_instance.app.public_ip}"
}
