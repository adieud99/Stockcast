# ============================================================
# 월 예산 알람.
#
# 프리티어가 끝난 뒤에는 켜 두는 것만으로 돈이 나간다.
# 인스턴스를 하나 더 띄웠거나 스토리지가 자동 확장되면 조용히 늘어나는데,
# 청구서를 볼 때는 이미 한 달이 지난 뒤다. 미리 알려 주게 한다.
#
# 계정당 예산 2개까지 무료다. 여기서는 1개만 쓴다.
# ============================================================

resource "aws_budgets_budget" "monthly" {
  count = var.monthly_budget_usd > 0 && var.alarm_email != "" ? 1 : 0

  name         = "${var.project}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # 실제로 쓴 금액이 80%를 넘으면 알린다. 아직 손쓸 수 있는 시점이다.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alarm_email]
  }

  # 이번 달 추세대로 가면 한도를 넘겠다 싶을 때 미리 알린다.
  # 실제 금액 알람만 두면 이미 다 쓴 뒤에 온다.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alarm_email]
  }
}
