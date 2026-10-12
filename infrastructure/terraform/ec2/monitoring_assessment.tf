# AWS DevOps assessment: two alarms -> SNS. This file intentionally reuses existing resources.
variable "monitoring_interviewer_email" {
  description = "Optional email recipient. Must confirm AWS SNS subscription email."
  type        = string
  default     = ""
  validation {
    condition     = var.monitoring_interviewer_email == "" || can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.monitoring_interviewer_email))
    error_message = "Provide a valid email address or an empty string."
  }
}

resource "aws_sns_topic" "assessment_alerts" {
  name = "${var.deployment_id}-alerts"
}

resource "aws_sns_topic_subscription" "assessment_email" {
  count     = var.monitoring_interviewer_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.assessment_alerts.arn
  protocol  = "email"
  endpoint  = var.monitoring_interviewer_email
}

resource "aws_cloudwatch_metric_alarm" "assessment_ec2_cpu" {
  alarm_name          = "${var.deployment_id}-ec2-high-cpu"
  alarm_description   = "EC2 CPU above 80 percent for 10 minutes"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  treat_missing_data  = "missing"
  dimensions          = { InstanceId = aws_instance.app.id }
  alarm_actions       = [aws_sns_topic.assessment_alerts.arn]
  ok_actions          = [aws_sns_topic.assessment_alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "assessment_unhealthy_targets" {
  alarm_name          = "${var.deployment_id}-alb-unhealthy-targets"
  alarm_description   = "ALB target group has unhealthy targets"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = aws_lb.app.arn_suffix
    TargetGroup  = aws_lb_target_group.app.arn_suffix
  }
  alarm_actions = [aws_sns_topic.assessment_alerts.arn]
  ok_actions    = [aws_sns_topic.assessment_alerts.arn]
}

output "assessment_alert_topic_arn" {
  description = "SNS topic for CloudWatch alarm notifications"
  value       = aws_sns_topic.assessment_alerts.arn
}
