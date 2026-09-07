# ============================================================
# 서버 자동 복구 — CloudWatch 알람으로 EC2를 되살린다.
#
# EC2 상태 검사는 두 종류이고, 고장 원인이 달라서 대응도 다르다.
#
#   StatusCheckFailed_System   AWS 쪽 문제(호스트 하드웨어·네트워크·전원).
#                              인스턴스를 다른 호스트로 옮겨야 한다 → recover
#   StatusCheckFailed_Instance 인스턴스 안 문제(커널 패닉, 파일시스템 손상,
#                              네트워크 설정 깨짐). 재부팅으로 푼다 → reboot
#
# 짚고 갈 것: System 쪽 복구는 요즘 AWS가 기본으로 켜 준다(simplified automatic
# recovery). 그래서 아래 recover 알람은 복구 자체보다 "언제 무슨 일이 있었는지
# 알람으로 남긴다"는 쪽에 값어치가 있다.
# 반대로 Instance 쪽 reboot 은 기본 동작이 아니라서, 이건 실제로 추가되는 안전장치다.
#
# 알람은 계정당 10개까지 무료다. 여기서는 3개를 쓴다.
# ============================================================

# 1) 호스트 장애 → 다른 하드웨어로 옮겨 되살린다.
#    EIP·인스턴스 ID·EBS 볼륨은 그대로 유지된다.
resource "aws_cloudwatch_metric_alarm" "system_recover" {
  count             = var.enable_autorecovery ? 1 : 0
  alarm_name        = "${var.project}-ec2-system-failed-recover"
  alarm_description = "EC2 호스트 장애. 인스턴스를 정상 하드웨어로 이전한다."

  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = aws_instance.app.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2 # 1분 간격 2회 연속. 순간적인 값 튐으로 복구가 돌지 않게.
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "missing" # 데이터가 없다고 장애로 보지 않는다.

  alarm_actions = ["arn:aws:automate:${var.aws_region}:ec2:recover"]

  tags = { Project = var.project }
}

# 2) 인스턴스 내부 장애 → 재부팅.
#    커널이 멈췄거나 부팅 볼륨이 깨졌을 때 사람 손 없이 한 번 되살려 본다.
resource "aws_cloudwatch_metric_alarm" "instance_reboot" {
  count             = var.enable_autorecovery ? 1 : 0
  alarm_name        = "${var.project}-ec2-instance-failed-reboot"
  alarm_description = "EC2 인스턴스 내부 상태검사 실패. 재부팅한다."

  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  dimensions          = { InstanceId = aws_instance.app.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3 # recover 보다 한 단계 느슨하게. 재부팅은 서비스가 끊긴다.
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "missing"

  alarm_actions = ["arn:aws:automate:${var.aws_region}:ec2:reboot"]

  tags = { Project = var.project }
}

# 3) 디스크가 차오르는 건 자동으로 못 고친다. 알려주기만 한다.
#    로그와 도커 이미지가 쌓여 루트 볼륨이 꽉 차면 컨테이너가 통째로 멈춘다.
#
#    기본값을 끄기(false)로 뒀다. 두 가지 이유다.
#      1) EBS 사용률은 기본 지표에 없다. EC2 안에 CloudWatch Agent 를 따로 깔아야 한다
#      2) 사용자 지표는 개당 월 $0.30 이 붙는다. 프리티어가 끝나면 그대로 청구된다
#    켜려면 enable_disk_alarm = true 로 두고 에이전트를 설치해야 한다.
resource "aws_cloudwatch_metric_alarm" "disk_space" {
  count             = var.enable_disk_alarm && var.alarm_email != "" ? 1 : 0
  alarm_name        = "${var.project}-ec2-disk-usage"
  alarm_description = "루트 볼륨 사용률 85% 초과. 로그·도커 이미지 정리가 필요하다."

  namespace   = "CWAgent"
  metric_name = "disk_used_percent"
  dimensions = {
    InstanceId = aws_instance.app.id
    path       = "/"
    fstype     = "xfs"
  }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching" # 에이전트를 안 깔았으면 조용히 넘어간다.

  alarm_actions = [aws_sns_topic.alerts[0].arn]

  tags = { Project = var.project }
}

# 알림 메일. alarm_email 을 비워 두면 SNS 자체를 만들지 않는다.
resource "aws_sns_topic" "alerts" {
  count = var.enable_autorecovery && var.alarm_email != "" ? 1 : 0
  name  = "${var.project}-alerts"
  tags  = { Project = var.project }
}

resource "aws_sns_topic_subscription" "alerts_email" {
  count     = var.enable_autorecovery && var.alarm_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alarm_email
  # 메일로 온 확인 링크를 눌러야 실제로 구독이 시작된다.
}
