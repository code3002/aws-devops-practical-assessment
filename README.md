# aws-devops-practical-assessment

End-to-end AWS DevOps assessment using Terraform, Docker, EKS, CI/CD and monitoring.

The approved application stacks are Node.js 24 + Express on EC2 and a separate Python application on EKS. Application and workload infrastructure are not implemented yet.

The [Terraform bootstrap runbook](infrastructure/terraform/bootstrap/README.md) covers the eight provisioned bootstrap resources, verified S3 state migration and DynamoDB locking, Git mirroring, recovery and cleanup dependencies. Terraform lives under `infrastructure/terraform/`; this contains the assessment's requested Terraform deliverables.

GitHub and CodeCommit authentication/reachability are verified. The CodeCommit repository has no refs yet: mirroring is not live until an approved push and matching remote SHA checks. Automatic teardown remains mandatory and unimplemented; it must precede larger EC2/EKS deployment.
