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
  description = "EC2 인스턴스 타입 (프리티어: t2.micro/t3.micro)"
  type        = string
  default     = "t3.micro"
}

variable "key_pair_name" {
  description = "SSH 접속용 기존 EC2 Key Pair 이름 (콘솔에서 미리 생성)"
  type        = string
}

variable "my_ip" {
  description = "SSH(22) 허용할 내 공인 IP (예: 1.2.3.4/32)"
  type        = string
}

variable "repo_url" {
  description = "EC2가 clone할 GitHub 저장소 URL (public 또는 토큰 포함)"
  type        = string
}

variable "db_password" {
  description = "PostgreSQL 비밀번호"
  type        = string
  sensitive   = true
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
