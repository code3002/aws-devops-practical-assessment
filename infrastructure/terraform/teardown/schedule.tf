locals {
  deadline_check_at = plantimestamp()
  schedule_configuration = {
    schedule_expression          = "at(${formatdate("YYYY-MM-DD'T'hh:mm:ss", local.teardown_expires_at)})"
    schedule_expression_timezone = "UTC"
    flexible_time_window         = { mode = "OFF" }
    state                        = var.TEARDOWN_ENABLED ? "ENABLED" : "DISABLED"
  }
}

output "schedule_configuration" {
  description = "Validated configuration used by the Scheduler resource."
  value       = local.schedule_configuration

  precondition {
    condition     = !var.TEARDOWN_ENABLED || timecmp(local.teardown_expires_at, local.deadline_check_at) > 0
    error_message = "An enabled teardown deadline must be strictly in the future. Extend TTL_HOURS intentionally or disable teardown; the start time is never reset."
  }
}
