mock_provider "aws" {}

variables {
  DEPLOYMENT_ID         = "test-teardown"
  SOURCE_COMMIT_SHA     = "5890ed075b9a04b947ee87102a77da9d41be070b"
  BACKEND_BUCKET        = "test-assessment-state"
  LOCK_TABLE            = "test-assessment-locks"
  DEPLOYMENT_STARTED_AT = "2099-10-11T12:00:00Z"
  AWS_ACCOUNT_ID        = "123456789012"
}

run "default_schedule" {
  command = plan
  assert {
    condition     = output.schedule_configuration.schedule_expression == "at(2099-10-13T12:00:00)" && output.schedule_configuration.schedule_expression_timezone == "UTC" && output.schedule_configuration.flexible_time_window.mode == "OFF" && output.schedule_configuration.state == "ENABLED"
    error_message = "Default schedule must match fixed 48-hour UTC expiry with no flexible window."
  }
}

run "extended_schedule" {
  command = plan
  variables {
    TTL_HOURS = 72
  }
  assert {
    condition     = output.schedule_configuration.schedule_expression == "at(2099-10-14T12:00:00)" && output.effective_start_time == run.default_schedule.effective_start_time
    error_message = "Explicit TTL extension must preserve start and move schedule expiry."
  }
}

run "disabled_past_schedule" {
  command = plan
  variables {
    TEARDOWN_ENABLED      = false
    DEPLOYMENT_STARTED_AT = "2000-10-11T12:00:00Z"
  }
  assert {
    condition     = output.schedule_configuration.state == "DISABLED" && output.schedule_configuration.schedule_expression == "at(2000-10-13T12:00:00)"
    error_message = "Disabled expired schedules must remain representable without shifting deadline."
  }
}

run "past_deadline_rejected" {
  command = plan
  variables {
    DEPLOYMENT_STARTED_AT = "2000-10-11T12:00:00Z"
  }
  expect_failures = [output.schedule_configuration]
}

run "repeat_schedule" {
  command = plan
  assert {
    condition     = output.schedule_configuration == run.default_schedule.schedule_configuration && output.effective_start_time == run.default_schedule.effective_start_time
    error_message = "Later ordinary plans must not reset the anchor or schedule."
  }
}

run "invalid_start" {
  command = plan
  variables {
    DEPLOYMENT_STARTED_AT = "not-a-timestamp"
  }
  expect_failures = [var.DEPLOYMENT_STARTED_AT]
}

run "invalid_ttl" {
  command = plan
  variables {
    TTL_HOURS = 0
  }
  expect_failures = [var.TTL_HOURS]
}
