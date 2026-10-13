mock_provider "aws" {}

override_resource {
  override_during = plan
  target          = aws_lambda_function.trigger
  values          = { arn = "arn:aws:lambda:ap-south-1:123456789012:function:test-teardown-ttl-trigger" }
}

override_resource {
  override_during = plan
  target          = aws_cloudwatch_log_group.trigger
  values          = { arn = "arn:aws:logs:ap-south-1:123456789012:log-group:/aws/lambda/test-teardown-ttl-trigger" }
}

variables {
  DEPLOYMENT_ID         = "test-teardown"
  EC2_DEPLOYMENT_ID     = "test-ec2"
  EKS_CLUSTER_NAME      = "test-eks-eks"
  BACKEND_BUCKET        = "test-assessment-state"
  LOCK_TABLE            = "test-assessment-locks"
  DEPLOYMENT_STARTED_AT = "2099-10-11T12:00:00Z"
  AWS_ACCOUNT_ID        = "123456789012"
  # Pin everything a private terraform.tfvars in this directory could set.
  TTL_HOURS               = 48
  TEARDOWN_ENABLED        = false
  EXECUTION_MODE          = "PREFLIGHT_ONLY"
  EXTRA_IAM_NAME_PREFIXES = []
}

run "scheduler_invokes_lambda_trigger" {
  command = plan
  assert {
    condition     = aws_lambda_function.trigger.environment[0].variables.PROJECT_NAME == "test-teardown-destroy" && aws_lambda_function.trigger.environment[0].variables.DEADLINE == "2099-10-13T12:00:00Z" && jsondecode(aws_scheduler_schedule.teardown.target[0].input).source == "scheduler"
    error_message = "Scheduler must invoke the Lambda trigger with the fixed deadline and destroy project."
  }
  assert {
    condition     = jsondecode(aws_iam_role_policy.start_destroy.policy).Statement[0].Action == "lambda:InvokeFunction" && jsondecode(aws_iam_role_policy.trigger.policy).Statement[0].Action == "codebuild:StartBuild" && jsondecode(aws_iam_role_policy.trigger.policy).Statement[0].Resource == "arn:aws:codebuild:ap-south-1:123456789012:project/test-teardown-destroy"
    error_message = "Scheduler may only invoke the trigger; the trigger may only start the destroy project."
  }
}

run "executor_project" {
  command = plan
  assert {
    condition     = aws_codebuild_project.destroy.source[0].buildspec == "scripts/teardown/buildspec.yml" && aws_codebuild_project.destroy.source_version == "refs/heads/main" && !aws_codebuild_project.destroy.environment[0].privileged_mode
    error_message = "Executor must run the committed teardown buildspec without privileged mode."
  }
  assert {
    condition     = [for entry in jsondecode([for variable in aws_codebuild_project.destroy.environment[0].environment_variable : variable.value if variable.name == "STACK_ORDER"][0]) : entry.stack] == ["cicd", "eks-workloads", "eks-addons", "eks", "route53", "ec2"]
    error_message = "Destroy order must remove CI, Kubernetes-created resources and EKS before DNS and the shared VPC."
  }
  assert {
    condition     = [for variable in aws_codebuild_project.destroy.environment[0].environment_variable : variable.value if variable.name == "EXECUTION_MODE"][0] == "PREFLIGHT_ONLY"
    error_message = "Default mode must be preflight."
  }
}

run "destroy_policy_is_scoped" {
  command = plan
  assert {
    condition     = one([for statement in local.build_permissions.Statement : statement.Condition if statement.Sid == "DestroyRegionalResources"]) == { StringEquals = { "aws:RequestedRegion" = "ap-south-1" } }
    error_message = "Regional destroy permissions must be limited to ap-south-1."
  }
  assert {
    condition     = alltrue([for arn in one([for statement in local.build_permissions.Statement : statement.Resource if statement.Sid == "DestroyProjectIam"]) : can(regex("^arn:aws:iam::123456789012:(role|policy|instance-profile)/(test-ec2-|test-eks-eks|KarpenterNodeRole-test-eks-eks|KarpenterController)", arn))])
    error_message = "IAM write access must be limited to this project's name prefixes."
  }
  assert {
    condition     = toset([for statement in local.build_permissions.Statement : statement.Sid if statement.Effect == "Deny"]) == toset(["ProtectBackend", "ProtectLocks", "ProtectMirror", "ProtectExecutor", "ProtectExecutorProject"])
    error_message = "State bucket, lock table, CodeCommit mirror and executor identities must be explicitly protected."
  }
}

run "destroy_mode" {
  command = plan
  variables {
    EXECUTION_MODE = "DESTROY"
  }
  assert {
    condition     = [for variable in aws_codebuild_project.destroy.environment[0].environment_variable : variable.value if variable.name == "EXECUTION_MODE"][0] == "DESTROY"
    error_message = "DESTROY must reach the executor."
  }
}

run "invalid_mode" {
  command = plan
  variables {
    EXECUTION_MODE = "DESTROY_FULL_STACK"
  }
  expect_failures = [var.EXECUTION_MODE]
}
