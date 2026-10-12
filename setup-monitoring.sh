#!/usr/bin/env bash
set -euo pipefail

# Adds CloudWatch alarms + SNS to existing EC2 Terraform stack, without altering existing resources.
# AWS mutations happen only after explicit confirmation.
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
STACK="$ROOT/infrastructure/terraform/ec2"
REGION="${AWS_REGION:-ap-south-1}"
EMAIL="${INTERVIEWER_EMAIL:-}"
FILE="$STACK/monitoring_assessment.tf"

fail(){ echo "ERROR: $*" >&2; exit 1; }
[[ -d "$STACK" ]] || fail "Missing Terraform EC2 directory: $STACK"
command -v terraform >/dev/null || fail 'terraform is required'
command -v aws >/dev/null || fail 'aws CLI is required'
[[ -f "$STACK/main.tf" || -n "$(find "$STACK" -maxdepth 1 -name '*.tf' -print -quit)" ]] || fail 'No Terraform configuration found'
[[ ! -e "$FILE" ]] || fail "$FILE already exists; inspect it rather than overwrite"
[[ -z "$(git -C "$ROOT" status --porcelain)" ]] || fail 'Working tree is not clean. Commit/stash changes before running.'

# Confirm known resource names are actually declared in this stack.
for declaration in 'resource "aws_instance" "app"' 'resource "aws_lb_target_group" "app"' 'resource "aws_lb" "app"'; do
  grep -Eq "${declaration}" "$STACK"/*.tf || fail "Expected Terraform declaration not found: $declaration"
done

if [[ -n "$EMAIL" && ! "$EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]; then
  fail 'INTERVIEWER_EMAIL is not a valid email address'
fi

cat > "$FILE" <<'HCL'
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
HCL

cleanup(){
  if [[ "${APPLIED:-false}" != true ]]; then
    echo "Terraform file left for review: $FILE"
  fi
}
trap cleanup EXIT

terraform -chdir="$STACK" fmt -check -diff || terraform -chdir="$STACK" fmt "$FILE"
terraform -chdir="$STACK" init -input=false
terraform -chdir="$STACK" validate
PLAN="$(mktemp -t assessment-monitoring.XXXXXX.tfplan)"
trap 'rm -f "${PLAN:-}"; cleanup' EXIT

ARGS=()
if [[ -n "$EMAIL" ]]; then ARGS+=("-var=monitoring_interviewer_email=$EMAIL"); fi
terraform -chdir="$STACK" plan -input=false -out="$PLAN" "${ARGS[@]}"
echo
printf 'Inspect the plan. Expected additions: 1 SNS topic, 2 CloudWatch alarms%s.\n' "$( [[ -n "$EMAIL" ]] && echo ', 1 email subscription' || true )"
echo 'No existing resource should be replaced or destroyed.'
read -r -p 'Type APPLY to execute this Terraform plan (anything else cancels): ' answer
if [[ "$answer" != 'APPLY' ]]; then echo 'Canceled: no AWS changes applied.'; exit 0; fi
terraform -chdir="$STACK" apply -input=false "$PLAN"
APPLIED=true

echo '=== CloudWatch alarms ==='
aws cloudwatch describe-alarms --region "$REGION" \
  --alarm-name-prefix "${TF_VAR_deployment_id:-aws-devops-assessment-ec2-01}-" \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Actions:AlarmActions}' --output table

echo '=== SNS topic ==='
terraform -chdir="$STACK" output -raw assessment_alert_topic_arn
if [[ -n "$EMAIL" ]]; then
  echo "Check $EMAIL for SNS subscription confirmation; pending confirmation means notifications are NOT active."
else
  echo 'No email configured. Set INTERVIEWER_EMAIL and rerun terraform plan/apply to add subscription.'
fi

echo 'DONE: CloudWatch + SNS Terraform applied. Prometheus exporters are NOT installed by this script.'
