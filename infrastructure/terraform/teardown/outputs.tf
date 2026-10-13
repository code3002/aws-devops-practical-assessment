locals {
  teardown_expires_at = timeadd(var.DEPLOYMENT_STARTED_AT, "${var.TTL_HOURS}h")
}

output "effective_start_time" {
  description = "Fixed UTC start from retained configuration."
  value       = var.DEPLOYMENT_STARTED_AT
}

output "expiry_time" {
  description = "Fixed start plus TTL_HOURS: when the schedule fires."
  value       = local.teardown_expires_at
}

output "teardown_enabled" {
  value = var.TEARDOWN_ENABLED
}

output "cancellation_status" {
  description = "Requested schedule status."
  value       = var.TEARDOWN_ENABLED ? "enabled" : "cancelled"
}

output "execution_mode" {
  value = var.EXECUTION_MODE
}

output "destroy_role_arn" {
  description = "Pass to the eks stack as teardown_role_arn so the executor can clean up Kubernetes-created AWS resources."
  value       = aws_iam_role.destroy.arn
}

output "destroy_project_name" {
  value = aws_codebuild_project.destroy.name
}

output "trigger_function_name" {
  value = aws_lambda_function.trigger.function_name
}

output "stack_order" {
  value = [for entry in local.stack_order : entry.stack]
}
