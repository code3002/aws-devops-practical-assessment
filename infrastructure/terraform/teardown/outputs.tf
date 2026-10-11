locals {
  teardown_expires_at = timeadd(var.DEPLOYMENT_STARTED_AT, "${var.TTL_HOURS}h")
}

output "effective_start_time" {
  description = "Fixed UTC start from retained configuration."
  value       = var.DEPLOYMENT_STARTED_AT
}

output "expiry_time" {
  description = "Fixed start plus configured TTL; retained even while cancellation is enabled."
  value       = local.teardown_expires_at
}

output "teardown_enabled" {
  value = var.TEARDOWN_ENABLED
}

output "cancellation_status" {
  description = "Requested policy status, not proof of an AWS schedule update."
  value       = var.TEARDOWN_ENABLED ? "enabled" : "cancelled"
}
