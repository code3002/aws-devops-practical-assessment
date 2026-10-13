# AWS DevOps Practical Assessment

This repository is a hands-on AWS DevOps assessment. It has two independent runtime paths that share one custom VPC in `ap-south-1`:

| Path | Workload | Platform | Delivery |
| --- | --- | --- | --- |
| **EC2 path** (brief  4,  5,  7,  8) | Node.js 24 + Express clock with a PostgreSQL read/write endpoint | Docker Compose (Nginx + app + Prometheus + exporters) on one Amazon Linux 2023 EC2 instance behind an internet-facing ALB, with private RDS PostgreSQL | CodeCommit push → EventBridge → CodeBuild → S3 versioned artifacts → SSM Run Command |
| **EKS path** (brief  2) | Python (Flask + Gunicorn) clock | Amazon EKS with a managed system node group, AWS Load Balancer Controller (Gateway API), Karpenter and a Strimzi Kafka cluster | Manual `docker push` to ECR and `kubectl apply` (no EKS CI/CD) |

Supporting capabilities: Terraform remote state in S3 with DynamoDB locking, a CodeCommit mirror of the GitHub repository, a Route 53 delegated subdomain, CloudWatch alarms that notify SNS, and a guarded EventBridge Scheduler → CodeBuild teardown executor.

The authoritative specification is [`docs/assessment_brief.pdf`](docs/assessment_brief.pdf). This README describes what the code in this repository does. When the README says something is **verified**, it gives the evidence. Configuration that exists only in code is never described as operational.

---

## Contents

1. [Project Overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Repository Structure](#4-repository-structure)
5. [AWS Configuration](#5-aws-configuration)
6. [Deployment Guide](#6-deployment-guide--step-by-step)
7. [Application Endpoints](#7-application-endpoints)
8. [Testing and Validation](#8-testing-and-validation)
9. [Troubleshooting](#9-troubleshooting)
10. [Cleanup and Cost Management](#10-cleanup-and-cost-management)
11. [Security Considerations](#11-security-considerations)
12. [Assessment Verification Checklist](#12-assessment-verification-checklist)
13. [Known Gaps and Repository Inconsistencies](#13-known-gaps-and-repository-inconsistencies)

---

## 1. Project Overview

### Objectives (from the brief)

- Provision AWS infrastructure with Terraform, with no console-created resources.
- Containerise a dynamic web application behind an Nginx reverse proxy that sets security headers.
- Run a second, independent Python workload on EKS, exposed through the Kubernetes Gateway API, with Karpenter and a Strimzi Kafka cluster.
- Mirror the source to CodeCommit, and build and deploy on every push.
- Monitor with CloudWatch alarms that notify SNS, plus Prometheus scraping node and Nginx metrics.
- Tear everything down automatically after a configurable TTL (default 48 hours).

### Implemented capabilities

| Capability | Implementation |
| --- | --- |
| Remote state | S3 bucket (versioned, SSE-S3, TLS-only, public access blocked) + DynamoDB `LockID` table: `infrastructure/terraform/bootstrap` |
| Source mirror | CodeCommit repository `aws-devops-practical-assessment` (bootstrap stack) |
| Network | VPC `10.10.0.0/16`, 2 public + 2 private subnets in two AZs, IGW, one NAT gateway: `infrastructure/terraform/ec2/main.tf` |
| EC2 workload | `t3.small` AL2023 instance in `public_a`, IMDSv2 required, encrypted gp3 root, SSM-managed (no SSH ingress rule) |
| Load balancing | Internet-facing ALB, HTTP :80, target health check on `/health` |
| Database | RDS PostgreSQL `db.t4g.micro`, private subnets, encrypted, not publicly accessible, master password managed by RDS in Secrets Manager |
| App delivery | Private versioned S3 artifact bucket, SSM Command document that installs checksum-verified helper scripts |
| CI/CD | EventBridge rule on CodeCommit `main` → CodeBuild (`buildspec.yml`) → `scripts/deploy/codebuild_deploy.sh` → SSM |
| EKS | EKS cluster in the **existing** VPC's private subnets, managed `system` node group, add-ons vpc-cni, coredns, kube-proxy, eks-pod-identity-agent, aws-ebs-csi-driver |
| Gateway API | `GatewayClass` `aws-alb`, `Gateway` + `HTTPRoute`, AWS `LoadBalancerConfiguration` and `TargetGroupConfiguration` |
| Karpenter | `EC2NodeClass` + `NodePool` restricted to `t3.medium` on-demand amd64 |
| Kafka | Strimzi operator via Helm (chart `1.2.0`), KRaft single combined broker/controller, topic `assessment-events` |
| DNS | Route 53 hosted zone `aws.rahulbagal.tech` with `app.` (EC2 ALB) and `eks.` (Gateway ALB) alias records |
| Monitoring | CloudWatch alarms for EC2 CPU > 80% and ALB `UnHealthyHostCount` > 0 → SNS email topic. Prometheus + node_exporter + nginx-prometheus-exporter in Compose |
| Teardown | EventBridge Scheduler one-time `at()` schedule → CodeBuild destroy project. Preflight-only by default, with multiple safety gates |

### Technologies and pinned versions (from source)

| Component | Version | Source |
| --- | --- | --- |
| Terraform | `= 1.15.8` (bootstrap, ec2, eks, teardown); `>= 1.5.0` (cicd, route53) | `versions.tf` / `main.tf` |
| AWS provider | `= 6.21.0` (bootstrap, ec2, eks, teardown); `~> 5.0`, locked `5.100.0` (cicd, route53) | `versions.tf`, `.terraform.lock.hcl` |
| Node.js app image | `public.ecr.aws/docker/library/node:24.11.1-bookworm-slim`, Express `5.1.0`, pg `8.16.3` | `app/Dockerfile`, `app/package.json` |
| Python app image | `python:3.12-slim`, Flask `3.1.1`, Gunicorn `23.0.0` | `apps/python-time/` |
| Nginx | `nginx:1.28.0-alpine` | `docker-compose.yml` |
| Prometheus / exporters | `prom/prometheus:v3.5.0`, `prom/node-exporter:v1.9.1`, `nginx/nginx-prometheus-exporter:1.4.2` | `docker-compose.yml` |
| Docker Compose on EC2 | `2.39.4` (SHA-256 verified) | `scripts/host/bootstrap.sh` |
| CodeBuild image | `aws/codebuild/standard:7.0`, Node.js runtime 24 | `cicd/codebuild.tf`, `buildspec.yml` |
| Strimzi operator chart | `1.2.0` (`oci://quay.io/strimzi-helm/strimzi-kafka-operator`) | `infrastructure/kubernetes/kafka/install-operator.sh` |
| AWS Load Balancer Controller, Karpenter, Gateway API CRDs | **Not pinned in this repository** | see [ 13](#13-known-gaps-and-repository-inconsistencies) |

---

## 2. Architecture

![AWS Architecture](docs/architecture/aws-assessment-actual-architecture.drawio.png)

[Edit Architecture Diagram](docs/architecture/aws-assessment-actual-architecture.drawio). Open it in [diagrams.net](https://app.diagrams.net/).

> [!NOTE]
> The paths `docs/architecture/aws-architecture.svg` and `docs/architecture/aws-architecture.drawio` **do not exist** in this repository. The committed diagram is `docs/architecture/aws-assessment-actual-architecture.drawio` with a PNG export alongside it, and the links above point to those files. To publish the requested SVG paths, export the existing draw.io source to `docs/architecture/aws-architecture.svg` and save a copy as `docs/architecture/aws-architecture.drawio`.

### Shared VPC: EC2 and EKS

There is **one** VPC. The EKS stack creates no network resources. It reads the VPC and private subnets created by the EC2 stack through `data "aws_vpc"` / `data "aws_subnet"` lookups (`infrastructure/terraform/eks/network.tf`). A `check` block asserts that both subnets belong to that VPC and span two AZs.

| Subnet key (EC2 stack) | CIDR | Route | Used by |
| --- | --- | --- | --- |
| `public_a` | `10.10.0.0/24` | IGW | EC2 instance, EC2 ALB, NAT gateway, EKS Gateway ALB (controller-selected) |
| `public_b` | `10.10.1.0/24` | IGW | EC2 ALB, EKS Gateway ALB |
| `database_a` | `10.10.10.0/24` | NAT in `public_a` | RDS, EKS control-plane ENIs, EKS nodes, Karpenter nodes |
| `database_b` | `10.10.11.0/24` | NAT in `public_a` | RDS subnet group, EKS control-plane ENIs, EKS nodes, Karpenter nodes |

There are no separate "application private subnets". The two private subnets are named `database_*` and are reused for EKS. Egress goes through a single zonal NAT gateway, which is not a highly available design (see the comment in `main.tf`).

Because EKS depends on subnets owned by the EC2 state, **destroy EKS before EC2**, or the VPC destroy will hang on EKS/Karpenter/ALB ENIs.

### Terraform states and how they relate

All stacks use the same S3 bucket and DynamoDB lock table, each with its own state key.

| Stack | Directory | State key | Consumes from other stacks |
| --- | --- | --- | --- |
| bootstrap | `infrastructure/terraform/bootstrap` | `bootstrap/terraform.tfstate` | — (creates the bucket/table it is stored in; see Phase 1) |
| ec2 | `infrastructure/terraform/ec2` | `ec2/terraform.tfstate` | — |
| cicd | `infrastructure/terraform/cicd` | not defined in repo (suggested `cicd/terraform.tfstate`) | `terraform_remote_state` of the **ec2** key (`ec2_state_key`, default `ec2/terraform.tfstate`) |
| eks | `infrastructure/terraform/eks` | `eks/terraform.tfstate` | VPC and subnet IDs passed **as input variables** (copy them from ec2 outputs) |
| route53 | `infrastructure/terraform/route53` | not defined in repo (suggested `route53/terraform.tfstate`) | EC2 ALB looked up by tag `Name = aws-devops-assessment-ec2-01-app`. EKS ALB DNS name **hardcoded** in `eks-dns.tf` |
| teardown | `infrastructure/terraform/teardown` | `teardown/terraform.tfstate` (`STATE_KEYS.teardown`) | Explicit variables. The executor reads the bootstrap/teardown/ec2/eks keys |

```text
bootstrap ─► ec2 ─┬─► cicd        (remote_state: ec2 outputs)
                  ├─► eks         (inputs: vpc_id, private_subnet_ids)
                  │    └─► Kubernetes add-ons / workloads (kubectl, helm)
                  ├─► route53     (needs EC2 ALB and the Gateway ALB to exist)
                  └─► teardown    (needs CodeCommit SHA + bucket/table; points at ec2 and eks)
```

### Request and control flows

- **EC2 request:** client → Route 53 `app.aws.rahulbagal.tech` → ALB :80 (SG `alb`: 0.0.0.0/0:80) → EC2 :80 (SG `ec2`: only from the ALB SG) → Nginx container → `app:3000` → RDS :5432 (SG `rds`: only from the EC2 SG) over TLS with `verify-full`.
- **EKS request:** client → Route 53 `eks.aws.rahulbagal.tech` → Gateway-provisioned ALB → `HTTPRoute` → `Service python-time` (port 80) → pods on port 8000 (IP targets, health check `/health`).
- **Deployment:** `git push codecommit main` → EventBridge rule `<deployment_id>-codecommit-main` → CodeBuild `<deployment_id>-app-build` → `npm ci && npm test` → `docker build` → `docker save` and source archive to S3 (`images/<sha>.tar.gz`, `applications/<sha>.tar.gz`) → `ssm send-command` on the deployment document → host verifies hashes, loads the image and restarts Compose.
- **Monitoring:** Prometheus (`127.0.0.1:9090` on the host only) scrapes `node-exporter:9100` and `nginx-exporter:9113`. The exporter reads Nginx `stub_status` on the Compose-internal port 8080. CloudWatch alarms publish to SNS.

---

## 3. Prerequisites

### Required tools

The "tested" column lists the versions on the workstation used to write and check this README (macOS arm64, 2026-10-13). The repository pins only Terraform.

| Tool | Required version | Tested | Needed for |
| --- | --- | --- | --- |
| Terraform | **exactly 1.15.8** (pinned by `required_version`) | 1.15.8 | All stacks |
| AWS CLI v2 | v2 | 2.36.13 | Credentials, outputs, SSM, EKS kubeconfig, verification |
| Git | any recent | 2.54.0 | Clone, CodeCommit push (with the AWS CLI credential helper) |
| Docker Engine + Compose v2 | Compose v2 (`docker compose`) | Docker 29.8.2, Compose v5.5.1 | Building images, local Compose validation |
| Python 3 | ≥ 3.9 (standard library only) | 3.14.3 | Helper scripts and unit tests |
| Node.js | 24.x (`engines: >=24 <25`) | 24.11.1 | App unit tests (`npm test`) |
| kubectl | within ±1 minor of the cluster version | 1.37.1 | EKS path |
| Helm | v3 or later (OCI support required) | 4.3.0 | Strimzi, ALB Controller, Karpenter |

### Optional tools

| Tool | Purpose |
| --- | --- |
| AWS Session Manager plugin | `aws ssm start-session` and port-forwarding to Prometheus on the EC2 host |
| `dig` / `nslookup` | DNS verification |
| diagrams.net | Editing the architecture diagram |

### AWS account and permissions

- One AWS account and the **`ap-south-1`** region. Every stack except cicd and route53 validates the region, and the cleanup scripts hard-require it.
- An operator identity able to create and destroy: S3, DynamoDB, CodeCommit, VPC/EC2/ELBv2, RDS, Secrets Manager, SSM documents, IAM roles/policies/instance profiles, CloudWatch Logs/alarms, SNS, CodeBuild, EventBridge rules and Scheduler, EKS, ECR, CloudFormation (Karpenter IAM stack), SQS (Karpenter interruption queue) and Route 53. The repository does not ship a least-privilege operator policy.
- Service quotas for at least one `t3.small`, two or more `t3.medium` (system nodes) plus Karpenter `t3.medium` capacity, one `db.t4g.micro`, two ALBs, one NAT gateway and one Elastic IP.

### Domain and Route 53

- The route53 stack creates a **new public hosted zone `aws.rahulbagal.tech`** with records `app.aws.rahulbagal.tech` and `eks.aws.rahulbagal.tech`. These names are hardcoded in `infrastructure/terraform/route53/*.tf`.
- For the names to resolve publicly, the parent zone (`rahulbagal.tech`, hosted outside this repository) needs an `NS` delegation to the four name servers in the `name_servers` output. That step happens at the parent DNS provider and is **not automated here**.
- To use another domain, edit `name` in `route53/main.tf`, `ec2-dns.tf` and `eks-dns.tf` before applying.

---

## 4. Repository Structure

```text
.
├── README.md
├── buildspec.yml                       # CodeBuild: Node 24, npm test, docker build, deploy via SSM
├── docker-compose.yml                  # app, nginx, node-exporter, nginx-exporter, prometheus (config embedded)
├── .env.example                        # Placeholder PG* variables for local Compose
├── setup-monitoring.sh                 # One-shot generator that wrote ec2/monitoring_assessment.tf (already applied; refuses to overwrite)
├── setup-prometheus.sh                 # One-shot generator for Prometheus/exporter config (already applied; refuses to overwrite)
├── app/                                # EC2 workload: Express app, Dockerfile, tests, schema
│   ├── app.js  server.js  public/clock.js
│   ├── Dockerfile  package.json  package-lock.json  schema.sql
│   └── test/app.test.js
├── apps/python-time/                   # EKS workload: Flask app, Dockerfile, requirements
├── nginx/default.conf                  # Reverse proxy, security headers, internal stub_status :8080
├── monitoring/prometheus.yml           # Reference copy of the scrape config embedded in docker-compose.yml
├── kubernetes/python-time/deployment.yaml   # Deployment (2 replicas) + ClusterIP Service
├── infrastructure/
│   ├── kubernetes/
│   │   ├── aws-load-balancer-controller/   # IAM policy, Pod Identity trust policy, Helm values
│   │   ├── gateway-api/                    # AWS Gateway CRDs, GatewayClass/Gateway/HTTPRoute, TargetGroupConfiguration
│   │   ├── kafka/                          # Strimzi install script, KafkaNodePool/Kafka/KafkaTopic
│   │   └── storage/gp3.yaml                # EBS CSI gp3 StorageClass (used by Kafka PVC)
│   └── terraform/
│       ├── bootstrap/                      # CodeCommit, S3 state bucket, DynamoDB lock table
│       ├── ec2/                            # VPC, ALB, EC2, RDS, S3 artifacts, secret, SSM doc, alarms, SNS (+ mock tests)
│       ├── cicd/                           # CodeBuild app project, EventBridge rule, IAM
│       ├── eks/                            # EKS cluster, node group, add-ons, Karpenter/EBS CSI identities
│       │   └── karpenter/                  # Karpenter IAM/SQS CloudFormation template, EC2NodeClass + NodePool
│       ├── route53/                        # Hosted zone + app/eks alias records
│       └── teardown/                       # Scheduler, destroy CodeBuild project, IAM (+ mock tests)
│           └── executor/                   # Earlier read-only preflight executor and tests (not referenced by codebuild.tf)
├── scripts/
│   ├── host/bootstrap.sh                   # EC2 user data: Docker, Compose 2.39.4, SSM agent, /opt/assessment
│   ├── deploy/                             # Artifact packaging, SSM coordinator (prepare.py), host deploy/rollback (deploy.sh)
│   ├── database/                           # Secret population, DB role/schema initialisation, integration test harness
│   └── cleanup/                            # Teardown executor (codebuild.py, kubernetes.py, eks.py, ec2.py), publisher, tests
└── docs/
    ├── assessment_brief.pdf
    └── architecture/aws-assessment-actual-architecture.drawio(.png)
```

---

## 5. AWS Configuration

### Credentials and region

```bash
# Use any supported credential source (SSO, assumed role, environment). Never commit credentials.
aws configure sso            # or: export AWS_PROFILE=<your-profile>
export AWS_REGION=ap-south-1
export AWS_DEFAULT_REGION=ap-south-1

# Verify identity and region BEFORE any Terraform command
aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output table
aws configure get region
```

Every pinned stack sets `allowed_account_ids = [<expected account>]`, so Terraform refuses to run against any other account.

### Shell variables used in this guide

```bash
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export STATE_BUCKET="<globally-unique-state-bucket-name>"     # e.g. lowercase, 3-63 chars
export LOCK_TABLE="aws-devops-assessment-locks"               # bootstrap default
export EC2_DEPLOYMENT_ID="aws-devops-assessment-ec2-01"       # must match route53/ec2-dns.tf tag lookup
export EKS_DEPLOYMENT_ID="aws-devops-assessment-eks-01"       # cluster name becomes <id>-eks
export CLUSTER_NAME="${EKS_DEPLOYMENT_ID}-eks"
export MY_CIDR="$(curl -s https://checkip.amazonaws.com)/32"  # your public IPv4 /32
```

### Private input files

Each stack ships `*.example` files. Copy them to the ignored names (`*.tfvars` and `backend.hcl` are in `.gitignore`) and fill in placeholders:

| Stack | Copy | Required inputs |
| --- | --- | --- |
| bootstrap | `terraform.tfvars.example` → `terraform.tfvars`, `backend.hcl.example` → `backend.hcl` | `expected_account_id`, `state_bucket_name` (`repository_name`, `lock_table_name` have defaults) |
| ec2 | same two files | `expected_account_id`, `deployment_id`, `reviewer_ssh_cidr` (/24–/32, validation only, since no SSH rule is created), `reviewed_ami_id`, `postgres_version`. Optional: `monitoring_interviewer_email`, `ssh_key_name`, `artifact_bucket`, `app_secret_arn`, `ssm_document_name` |
| cicd | **no example files**; create them | `expected_account_id`, `deployment_id`, `state_bucket` (defaults: `aws_region`, `ec2_state_key`, `codecommit_repository_name`) |
| eks | same two files (**the committed examples contain real account/VPC/subnet/bucket identifiers; replace all of them**) | `expected_account_id`, `deployment_id`, `vpc_id`, `private_subnet_ids` (exactly 2), `kubernetes_version`, `cluster_public_access_cidrs` (not `0.0.0.0/0`). Optional: `node_instance_type` (`t3.medium`), `node_desired_size` (`2`) |
| route53 | **no example files and no variables** | Region/domain are hardcoded; supply only a backend config |
| teardown | same two files | `DEPLOYMENT_STARTED_AT`, `AWS_ACCOUNT_ID`, `DEPLOYMENT_ID`, `SOURCE_COMMIT_SHA`, `BACKEND_BUCKET`, `LOCK_TABLE`, plus the safety switches (see Phase 8) |

Helper look-ups for the ec2 inputs (read-only):

```bash
# Amazon-owned AL2023 x86_64 AMI (compute.tf requires name al2023-ami-*-x86_64, owner amazon)
aws ssm get-parameter --region ap-south-1 \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query Parameter.Value --output text

# PostgreSQL major.minor versions orderable on db.t4g.micro with gp3
aws rds describe-orderable-db-instance-options --region ap-south-1 \
  --engine postgres --db-instance-class db.t4g.micro \
  --query 'OrderableDBInstanceOptions[?StorageType==`gp3`].EngineVersion' --output text \
  | tr '\t' '\n' | sort -uV | tail -5

# EKS-supported Kubernetes versions
aws eks describe-cluster-versions --region ap-south-1 \
  --query 'clusterVersions[].clusterVersion' --output text
```

Secrets are never Terraform inputs. The RDS master password is generated by RDS (`manage_master_user_password = true`). The application secret is created as **metadata only** and populated by `scripts/database/populate_secret.py` (Phase 3).

---

## 6. Deployment Guide — Step by Step

> [!IMPORTANT]
> Every `terraform apply` below creates billable resources. Run `terraform plan`, review it, and apply only what you intend. All commands run from the repository root unless a `-chdir` is shown.

### Phase 0 — Clone

```bash
git clone <github-repository-url> aws-devops-practical-assessment
cd aws-devops-practical-assessment
```

---

### Phase 1 — Bootstrap (CodeCommit, S3 state, DynamoDB locking)

**Purpose:** Create the state bucket, lock table and CodeCommit mirror that every other stack depends on.

**Prerequisites:** Verified AWS identity and region ( 5).

**Dependency note:** `bootstrap/backend.tf` already declares `backend "s3" {}`, but the bucket does not exist yet. `backend.tf.example` says: *"Activate as backend.tf only AFTER approved creation of the bucket/table."* The first apply therefore uses local state, and the state is migrated afterwards.

**Commands:**

```bash
cd infrastructure/terraform/bootstrap
cp terraform.tfvars.example terraform.tfvars      # set expected_account_id and state_bucket_name
cp backend.hcl.example backend.hcl                # set bucket = <STATE_BUCKET>

# 1. First apply with LOCAL state: temporarily disable the S3 backend block
mv backend.tf backend.tf.disabled
terraform init
terraform plan -out=bootstrap.tfplan
terraform apply bootstrap.tfplan

# 2. Re-enable the backend and migrate local state into the new bucket
mv backend.tf.disabled backend.tf
terraform init -migrate-state -backend-config=backend.hcl
terraform output
cd ../../..
```

**Expected result:** Outputs `codecommit_clone_url_https`, `state_bucket_name`, `lock_table_name`, `aws_region`. After migration, `terraform plan` reports no changes.

**Verification:**

```bash
aws s3api get-bucket-versioning --bucket "$STATE_BUCKET"                  # Status: Enabled
aws s3api get-public-access-block --bucket "$STATE_BUCKET"
aws s3api head-object --bucket "$STATE_BUCKET" --key bootstrap/terraform.tfstate
aws dynamodb describe-table --table-name "$LOCK_TABLE" --query 'Table.{Status:TableStatus,Key:KeySchema}'
aws codecommit get-repository --repository-name aws-devops-practical-assessment \
  --query 'repositoryMetadata.cloneUrlHttp'
terraform -chdir=infrastructure/terraform/bootstrap plan -detailed-exitcode   # exit 0 = no drift
```

**Configure the CodeCommit mirror** (needed by Phases 4 and 8):

```bash
git config --local credential.https://git-codecommit.ap-south-1.amazonaws.com.helper '!aws codecommit credential-helper $@'
git config --local credential.https://git-codecommit.ap-south-1.amazonaws.com.UseHttpPath true
git remote add codecommit "$(terraform -chdir=infrastructure/terraform/bootstrap output -raw codecommit_clone_url_https)"
git push codecommit main
git fetch --all
git rev-parse HEAD origin/main codecommit/main     # all three SHAs should match
```

> Pushing `main` to CodeCommit **after** Phase 4 triggers a deployment. Pushing before Phase 4 only mirrors the code.

**Common failures:**

- `BucketAlreadyExists`: S3 bucket names are global. Choose another `state_bucket_name`.
- `Error: Backend initialization required` on the first run: `backend.tf` was not moved aside.
- `allowed_account_ids` error: the active credentials belong to a different account than `expected_account_id`.
- `git push` returns 403: the credential helper is not configured, or the identity lacks `codecommit:GitPush`.

---

### Phase 2 — EC2 infrastructure (shared VPC, ALB, EC2, RDS, delivery, alarms)

**Purpose:** Create the shared VPC and the complete EC2 runtime: subnets, IGW, NAT, security groups, ALB, EC2, RDS, artifact bucket, application secret metadata, SSM deployment document, SNS topic and CloudWatch alarms.

**Prerequisites:** Phase 1.

**Commands:**

```bash
cd infrastructure/terraform/ec2
cp terraform.tfvars.example terraform.tfvars
# Set: expected_account_id, deployment_id (= $EC2_DEPLOYMENT_ID), reviewer_ssh_cidr,
#      reviewed_ami_id, postgres_version, monitoring_interviewer_email (or "")
cp backend.hcl.example backend.hcl
# Set: bucket=<STATE_BUCKET>, key="ec2/terraform.tfstate", region="ap-south-1",
#      dynamodb_table=<LOCK_TABLE>, allowed_account_ids=["<ACCOUNT_ID>"]

terraform init -backend-config=backend.hcl
terraform plan -out=ec2.tfplan
terraform apply ec2.tfplan
terraform output
cd ../../..
```

**What gets created** (see `main.tf`, `security.tf`, `alb.tf`, `compute.tf`, `database.tf`, `delivery.tf`, `ssm.tf`, `iam.tf`, `monitoring_assessment.tf`):

- VPC `10.10.0.0/16`, subnets `public_a/b`, `database_a/b`, IGW, public and private route tables, EIP + NAT gateway in `public_a`.
- Security groups: ALB (80 from `0.0.0.0/0`), EC2 (80 from the ALB SG only, egress 80/443 + 5432 to RDS), RDS (5432 from the EC2 SG only). No port 22 rule.
- ALB + target group (`/health`, matcher `200`) + HTTP :80 listener + instance attachment.
- EC2 `t3.small`, user data `scripts/host/bootstrap.sh`, instance profile with `AmazonSSMManagedInstanceCore` and a runtime policy allowing `s3:GetObjectVersion` on `applications/*` and `images/*` and `secretsmanager:GetSecretValue` on the two secrets.
- RDS PostgreSQL `db.t4g.micro`, db `assessment`, master user `assessment_admin`, RDS-managed secret, **no backups, no final snapshot, no deletion protection** (disposable).
- S3 `<deployment_id>-<account>-artifacts` (versioned, private, TLS-only, `force_destroy = true`).
- Secrets Manager secret `<deployment_id>/application` (metadata only, `recovery_window_in_days = 0`).
- SSM document `<deployment_id>-app-deploy`.
- SNS topic `<deployment_id>-alerts`, an optional email subscription, and alarms `<deployment_id>-ec2-high-cpu` and `<deployment_id>-alb-unhealthy-targets`.

**Expected result:** Outputs include `vpc_id`, `subnet_ids`, `instance_id`, `alb_dns_name`, `database_address`, `database_secret_arn`, `application_secret_arn`, `artifact_bucket`, `deployment_document_name`, `assessment_alert_topic_arn`. The ALB target is **unhealthy** until Phase 3 deploys the application.

**Verification:**

```bash
cd infrastructure/terraform/ec2
INSTANCE_ID=$(terraform output -raw instance_id)
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[].PingStatus'                       # ["Online"]
aws rds describe-db-instances --db-instance-identifier "$(terraform output -raw database_identifier)" \
  --query 'DBInstances[0].{Status:DBInstanceStatus,Public:PubliclyAccessible,Encrypted:StorageEncrypted}'
aws ec2 describe-nat-gateways --nat-gateway-ids "$(terraform output -raw nat_gateway_id)" \
  --query 'NatGateways[0].State'
aws elbv2 describe-target-health --target-group-arn "$(terraform output -raw target_group_arn)"
cd ../../..
```

**Common failures:**

- `reviewed_ami_id` data source returns no results: the AMI is not Amazon-owned AL2023 x86_64 in `ap-south-1`.
- RDS `InvalidParameterCombination`: the `postgres_version` is not orderable with `db.t4g.micro` + gp3. Use the look-up in  5.
- SSM `PingStatus` missing: cloud-init is still running, or the user data failed. Check the console output with `aws ec2 get-console-output --instance-id "$INSTANCE_ID" --latest --output text | grep host-bootstrap`.

**Depends on:** Phase 1. **Required by:** Phases 3, 4, 5, 6, 7, 8.

---

### Phase 3 — First application deployment (database initialisation + SSM)

**Purpose:** Populate the application secret, create the least-privilege DB role and schema, and deploy the first immutable release. CI/CD (Phase 4) sends `"initialize": false` and **fails** with *"Initial database configuration is required"* until this phase has run once with `"initialize": true` (`scripts/deploy/prepare.py`).

**Prerequisites:** Phase 2, SSM `Online`, Docker, and a commit that exists locally (the artifact is built from Git objects, not the working tree).

**How it works:** `ssm send-command` passes a Base64 JSON `Configuration` to the SSM document. The document installs the SHA-256-verified helpers (`scripts/deploy/{prepare.py,deploy.sh,artifact.py}`, `scripts/database/{configure.py,initialize.cjs,initialize.sql}`) under `/opt/assessment/tools/<hash>` and runs `prepare.py`. It:

1. Downloads the regional RDS CA bundle and checks its SHA-256.
2. With `initialize: true`: downloads and verifies the source and image archives, runs `docker load`, then runs `configure.py`. That script reads the RDS master and application secrets, creates role `assessment_app` and table `messages` (`initialize.sql`) over TLS, and writes `/opt/assessment/runtime/app.env` (root, mode 0600).
3. Runs `deploy.sh`, which extracts the release to `/opt/assessment/releases/<sha>-<digest>`, starts Compose project `assessment-app`, checks health, and switches `/opt/assessment/current`.

**Commands:**

```bash
cd infrastructure/terraform/ec2
BUCKET=$(terraform output -raw artifact_bucket)
INSTANCE_ID=$(terraform output -raw instance_id)
DOC=$(terraform output -raw deployment_document_name)
DB_HOST=$(terraform output -raw database_address)
ADMIN_SECRET=$(terraform output -raw database_secret_arn)
APP_SECRET=$(terraform output -raw application_secret_arn)
cd ../../..
REV=$(git rev-parse HEAD)
RDS_CA_SHA256=ca4a9dc14e06c3f84274eff3ffed0e5d4d3463141593e1159eb4a0904df6cd74   # value used in cicd/codebuild.tf

# 1. Populate the application DB credential (dry run first, then --execute)
python3 scripts/database/populate_secret.py "$ACCOUNT_ID" "$APP_SECRET"
python3 scripts/database/populate_secret.py "$ACCOUNT_ID" "$APP_SECRET" --execute

# 2. Build the image for the x86_64 host (required when building on Apple Silicon)
docker build --platform linux/amd64 -t "assessment-app:$REV" ./app

# 3. Package and upload the image archive (writes ./assessment-image-$REV.tar.gz)
bash scripts/deploy/package_image.sh "$REV"
bash scripts/deploy/upload_image.sh "$REV" "$BUCKET"          # prints {"VersionId": ..., "ETag": ...}
IMAGE_VERSION=$(aws s3api head-object --bucket "$BUCKET" --key "images/$REV.tar.gz" --query VersionId --output text)
IMAGE_SHA256=$(shasum -a 256 "assessment-image-$REV.tar.gz" | awk '{print $1}')

# 4. Package and upload the source artifact (exact file list from scripts/deploy/artifact.py)
python3 scripts/deploy/artifact.py package "$REV" "source-$REV.tar.gz"
SOURCE_VERSION=$(aws s3api put-object --bucket "$BUCKET" --key "applications/$REV.tar.gz" \
  --body "source-$REV.tar.gz" --query VersionId --output text)
SOURCE_SHA256=$(shasum -a 256 "source-$REV.tar.gz" | awk '{print $1}')

# 5. Send the initial deployment (same JSON shape as scripts/deploy/codebuild_deploy.sh, initialize=true)
CONFIG=$(python3 - <<PY
import base64, json
print(base64.b64encode(json.dumps({
  "account": "$ACCOUNT_ID", "region": "ap-south-1", "host": "$DB_HOST",
  "admin_secret_arn": "$ADMIN_SECRET", "app_secret_arn": "$APP_SECRET",
  "ca_sha256": "$RDS_CA_SHA256", "bucket": "$BUCKET",
  "version_id": "$SOURCE_VERSION", "revision": "$REV", "artifact_sha256": "$SOURCE_SHA256",
  "image_version_id": "$IMAGE_VERSION", "image_sha256": "$IMAGE_SHA256",
  "initialize": True}, separators=(",", ":")).encode()).decode())
PY
)
COMMAND_ID=$(aws ssm send-command --document-name "$DOC" --instance-ids "$INSTANCE_ID" \
  --parameters "{\"Configuration\":[\"$CONFIG\"]}" --query Command.CommandId --output text)
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" || true
aws ssm get-command-invocation --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" \
  --query '{Status:Status,Out:StandardOutputContent,Err:StandardErrorContent}'

# Remove local archives
rm -f "assessment-image-$REV.tar.gz" "source-$REV.tar.gz"
```

**Expected result:** Status `Success` and output ending *"SSM deployment passed host HTTP health check; verify public ALB and database separately"*. The ALB target becomes `healthy`.

**Verification:**

```bash
ALB=$(terraform -chdir=infrastructure/terraform/ec2 output -raw alb_dns_name)
curl -s "http://$ALB/health"            # {"status":"ok"}
curl -s "http://$ALB/time"              # {"timestamp":"..."}
curl -sI "http://$ALB/" | grep -iE 'content-security-policy|x-frame-options|x-content-type-options|x-xss-protection'
# Database write + read-back through the app (stores a row; do not send sensitive data)
curl -s -X POST "http://$ALB/messages" -H 'Content-Type: application/json' -d '{"text":"hello"}'   # 201 {"id":..,"text":"hello"}
# Reflected-input safety: the response is JSON, never HTML
curl -s -X POST "http://$ALB/messages" -H 'Content-Type: application/json' -d '{"text":"<script>x</script>"}'
```

**Common failures:**

- `SSM deployment preparation failed; details withheld`: the helpers suppress details on purpose. Check `/opt/assessment` on the host (see  9) and confirm that the secret is populated, the artifact versions and SHA-256 values match, and the image was built for `linux/amd64`.
- `CA checksum mismatch`: AWS rotated the regional bundle. Recompute the SHA-256 of `https://truststore.pki.rds.amazonaws.com/ap-south-1/ap-south-1-bundle.pem` and update `RDS_CA_SHA256` (and `cicd/codebuild.tf`) after review.
- `upload_image.sh` uses `shasum` (macOS/Perl). On Linux, install `perl-Digest-SHA` or compute the hash with `sha256sum`.

> **Rollback:** each release is kept under `/opt/assessment/releases/` with a per-release image tag, and `deploy.sh` records `previous` before it switches `current`. To roll back, redeploy the previous commit's artifacts through SSM (with `initialize: false`) or let CodeBuild redeploy an earlier commit. Do not edit the host by hand.

---

### Phase 4 — CI/CD (CodeCommit → EventBridge → CodeBuild → SSM)

**Purpose:** Deploy every push to CodeCommit `main` to EC2 automatically.

**Prerequisites:** Phases 1–3 (the EC2 state must exist because `cicd/data.tf` reads it through `terraform_remote_state`).

**Commands:**

```bash
cd infrastructure/terraform/cicd
cat > terraform.tfvars <<EOF
expected_account_id = "<ACCOUNT_ID>"
deployment_id       = "<EC2_DEPLOYMENT_ID>"
state_bucket        = "<STATE_BUCKET>"
EOF
cat > backend.hcl <<EOF
bucket         = "<STATE_BUCKET>"
key            = "cicd/terraform.tfstate"
region         = "ap-south-1"
encrypt        = true
dynamodb_table = "<LOCK_TABLE>"
EOF
terraform init -backend-config=backend.hcl
terraform plan -out=cicd.tfplan
terraform apply cicd.tfplan
cd ../../..
```

**What gets created:** CodeBuild project `<deployment_id>-app-build` (privileged Docker, `standard:7.0`, source = CodeCommit `main`, `buildspec.yml`) with environment variables taken from EC2 outputs, a 7-day log group `/aws/codebuild/<deployment_id>-app-build`, a CodeBuild role (GitPull, PutObject on `applications/*`/`images/*`, SendCommand on the one document and instance, GetCommandInvocation, logs), and EventBridge rule `<deployment_id>-codecommit-main` matching `referenceCreated`/`referenceUpdated` on branch `main` of repository `aws-devops-practical-assessment`.

**GitHub ↔ CodeCommit synchronisation:** this is manual. GitHub (`origin`) is the primary remote and CodeCommit is a mirror. Push to both:

```bash
git push origin main
git push codecommit main     # this push triggers the pipeline
git fetch --all && git rev-parse HEAD origin/main codecommit/main
```

**Build steps** (`buildspec.yml`): Node 24 runtime → `npm ci && npm test` in `app/` → `docker build -t assessment-app:$CODEBUILD_RESOLVED_SOURCE_VERSION ./app` → `scripts/deploy/codebuild_deploy.sh` (package, upload, `ssm send-command`, poll up to 25 minutes).

**Verification and log inspection:**

```bash
PROJECT="${EC2_DEPLOYMENT_ID}-app-build"
BUILD_ID=$(aws codebuild list-builds-for-project --project-name "$PROJECT" --query 'ids[0]' --output text)
aws codebuild batch-get-builds --ids "$BUILD_ID" \
  --query 'builds[0].{Status:buildStatus,Source:resolvedSourceVersion,Phases:phases[].{p:phaseType,s:phaseStatus}}'
aws logs tail "/aws/codebuild/$PROJECT" --since 1h
aws events list-targets-by-rule --rule "${EC2_DEPLOYMENT_ID}-codecommit-main"
```

**Expected result:** `buildStatus: SUCCEEDED`, `resolvedSourceVersion` equal to the pushed SHA, and log line `Deployment successful: <sha>`.

**Diagnosing a failed deployment:**

| Symptom in log | Meaning / action |
| --- | --- |
| Fails in `PRE_BUILD` | `npm ci`/`npm test` failed. Reproduce with `npm test --prefix app` |
| `AccessDenied` on `s3:PutObject` | Bucket/prefix mismatch. Run `terraform plan` in `cicd` after any ec2 output change |
| `Deployment failed: Failed` + JSON details | SSM failed on the host. Run `aws ssm get-command-invocation --command-id <id> --instance-id <id>` and see  9 |
| `Initial database configuration is required` (host) | Phase 3 has not been run with `initialize: true` |
| No build starts after a push | The push was to GitHub only, or not to `main`. Check the EventBridge rule and that the repository name matches |

**Depends on:** Phases 1–3.

---

### Phase 5 — EKS (cluster, add-ons, Python app, Gateway API, Karpenter, Kafka)

> [!WARNING]
> Several Phase 5 steps (Karpenter IAM CloudFormation stack, ALB Controller IAM role and Helm release, Gateway API CRDs, Karpenter Helm release, ECR repository, namespace) are **not managed by Terraform** in this repository, and their versions are **not pinned** here. The commands below are labelled. Those marked *reconstructed* follow the committed files but are not scripted in the repo. Replace every `<VERSION>` with a version you have checked for compatibility with your Kubernetes version.

**Purpose:** Run the Python clock on EKS behind a Gateway API ALB, with Karpenter worker capacity and Strimzi Kafka.

**Prerequisites:** Phase 2 (VPC/subnets), Helm, kubectl, Docker.

#### 5.1 Karpenter IAM prerequisites (CloudFormation; must precede EKS Terraform)

`eks/karpenter-identity.tf` attaches five managed policies named `KarpenterController*Policy-<cluster>` that **must already exist**. They come from `infrastructure/terraform/eks/karpenter/cloudformation.yaml`, which also creates `KarpenterNodeRole-<cluster>`, the SQS interruption queue `<cluster>` and the EventBridge rules.

```bash
# reconstructed: the template is committed, the deploy command is not scripted
aws cloudformation deploy \
  --stack-name "Karpenter-${CLUSTER_NAME}" \
  --template-file infrastructure/terraform/eks/karpenter/cloudformation.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides "ClusterName=${CLUSTER_NAME}"
```

#### 5.2 EKS Terraform

```bash
cd infrastructure/terraform/eks
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl
# Replace ALL committed values. Take vpc_id and the two database subnet IDs from the ec2 outputs:
terraform -chdir=../ec2 output -raw vpc_id
terraform -chdir=../ec2 output -json subnet_ids     # use database_a and database_b
# Set deployment_id=<EKS_DEPLOYMENT_ID>, kubernetes_version, cluster_public_access_cidrs=["<MY_CIDR>"]
# backend.hcl: bucket=<STATE_BUCKET>, key="eks/terraform.tfstate", dynamodb_table=<LOCK_TABLE>
terraform init -backend-config=backend.hcl
terraform plan -out=eks.tfplan
terraform apply eks.tfplan
terraform output
cd ../../..
```

Creates: cluster `<deployment_id>-eks` (private + public endpoint restricted to `cluster_public_access_cidrs`, auth mode `API_AND_CONFIG_MAP`, creator gets admin), cluster/node IAM roles, managed node group `system` (`t3.medium` ×2 by default, min 1 / max 3, label `workload=system`), add-ons `vpc-cni`, `coredns`, `kube-proxy`, `eks-pod-identity-agent`, `aws-ebs-csi-driver` (Pod Identity), and the Karpenter controller role + Pod Identity association (`kube-system/karpenter`).

#### 5.3 kubectl access

```bash
aws eks update-kubeconfig --region ap-south-1 --name "$CLUSTER_NAME"
kubectl get nodes -o wide                         # 2 Ready nodes from nodegroup "system"
kubectl get pods -n kube-system
aws eks list-addons --cluster-name "$CLUSTER_NAME"
```

Only the identity that created the cluster has admin access (`bootstrap_cluster_creator_admin_permissions = true`). To give a reviewer access, create an access entry. **This is not in Terraform:**

```bash
aws eks create-access-entry --cluster-name "$CLUSTER_NAME" --principal-arn <reviewer-iam-role-or-user-arn>
aws eks associate-access-policy --cluster-name "$CLUSTER_NAME" --principal-arn <reviewer-iam-role-or-user-arn> \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy --access-scope type=cluster
```

The reviewer's public IP must also be in `cluster_public_access_cidrs`.

#### 5.4 Storage class (required by the Kafka PVC)

```bash
kubectl apply -f infrastructure/kubernetes/storage/gp3.yaml
```

#### 5.5 AWS Load Balancer Controller with Gateway API

Committed: `iam-policy.json`, `trust-policy.json` (Pod Identity), `values.yaml` (`ALBGatewayAPI: true`, 2 replicas). `values.yaml` hardcodes `clusterName` and `vpcId`, so **edit both** for a new environment.

```bash
# reconstructed: IAM role and Pod Identity association (names are your choice)
aws iam create-policy --policy-name "${CLUSTER_NAME}-alb-controller" \
  --policy-document file://infrastructure/kubernetes/aws-load-balancer-controller/iam-policy.json
aws iam create-role --role-name "${CLUSTER_NAME}-alb-controller" \
  --assume-role-policy-document file://infrastructure/kubernetes/aws-load-balancer-controller/trust-policy.json
aws iam attach-role-policy --role-name "${CLUSTER_NAME}-alb-controller" \
  --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/${CLUSTER_NAME}-alb-controller"
aws eks create-pod-identity-association --cluster-name "$CLUSTER_NAME" \
  --namespace kube-system --service-account aws-load-balancer-controller \
  --role-arn "arn:aws:iam::${ACCOUNT_ID}:role/${CLUSTER_NAME}-alb-controller"

# reconstructed: Gateway API standard CRDs (not committed) and AWS Gateway CRDs (committed)
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/<GATEWAY_API_VERSION>/standard-install.yaml
kubectl apply -f infrastructure/kubernetes/gateway-api/aws-gateway-crds.yaml

# reconstructed: controller Helm release
helm repo add eks https://aws.github.io/eks-charts && helm repo update
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  --namespace kube-system --version <ALB_CONTROLLER_CHART_VERSION> \
  -f infrastructure/kubernetes/aws-load-balancer-controller/values.yaml --wait
kubectl -n kube-system rollout status deploy/aws-load-balancer-controller
```

#### 5.6 Python application

`kubernetes/python-time/deployment.yaml` hardcodes the image `<account>.dkr.ecr.ap-south-1.amazonaws.com/eks-python-time:v1`. **Replace the account ID** with yours. There is no Namespace manifest and no Terraform-managed ECR repository.

```bash
# reconstructed: ECR repository, image build and push
aws ecr create-repository --repository-name eks-python-time --image-scanning-configuration scanOnPush=true
aws ecr get-login-password | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.ap-south-1.amazonaws.com"
docker build --platform linux/amd64 -t "${ACCOUNT_ID}.dkr.ecr.ap-south-1.amazonaws.com/eks-python-time:v1" apps/python-time
docker push "${ACCOUNT_ID}.dkr.ecr.ap-south-1.amazonaws.com/eks-python-time:v1"

kubectl create namespace python-time
kubectl apply -f kubernetes/python-time/deployment.yaml
kubectl -n python-time rollout status deploy/python-time
kubectl -n python-time port-forward svc/python-time 8080:80 &   # optional local check
curl -s localhost:8080/time; kill %1
```

**Real-time refresh mechanism:** the page served at `/` runs a small JavaScript polling loop. It calls `fetch('/time')` every 1000 ms and writes `data.time` (UTC ISO-8601 from `datetime.now(timezone.utc)`) into `#clock` with `innerText`. `/health` returns `{"status":"healthy"}` and backs the readiness/liveness probes and the ALB target group health check.

#### 5.7 Gateway and HTTPRoute

```bash
kubectl apply -f infrastructure/kubernetes/gateway-api/python-time-targetgroup.yaml   # IP targets, /health
kubectl apply -f infrastructure/kubernetes/gateway-api/python-time-gateway.yaml       # LoadBalancerConfiguration, GatewayClass aws-alb, Gateway, HTTPRoute
kubectl get gatewayclass aws-alb
kubectl -n python-time get gateway python-time-gateway        # PROGRAMMED=True, ADDRESS=<alb dns>
kubectl -n python-time get httproute python-time-route -o jsonpath='{.status.parents[0].conditions}'
GATEWAY_ALB=$(kubectl -n python-time get gateway python-time-gateway -o jsonpath='{.status.addresses[0].value}')
curl -s "http://$GATEWAY_ALB/health"
```

Record `$GATEWAY_ALB`. Phase 6 needs it.

#### 5.8 Karpenter

Committed: `infrastructure/terraform/eks/karpenter/manifests/provisioning.yaml`. It contains `EC2NodeClass assessment` (role `KarpenterNodeRole-<cluster>`, AMI alias `al2023@latest`, subnets and security group **by hardcoded ID**) and `NodePool assessment` (instance type **only** `t3.medium`, on-demand, amd64, CPU limit 8, consolidation `WhenEmptyOrUnderutilized` after 5m). Edit the role name, subnet IDs and security group ID (`terraform -chdir=infrastructure/terraform/eks output -raw cluster_security_group_id`) before applying.

```bash
# reconstructed: allow Karpenter-launched nodes to join (no Terraform resource exists for this)
aws eks create-access-entry --cluster-name "$CLUSTER_NAME" --type EC2_LINUX \
  --principal-arn "arn:aws:iam::${ACCOUNT_ID}:role/KarpenterNodeRole-${CLUSTER_NAME}"

# reconstructed: Karpenter controller (Pod Identity association already created by Terraform)
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version <KARPENTER_VERSION> --namespace kube-system \
  --set "settings.clusterName=${CLUSTER_NAME}" \
  --set "settings.interruptionQueue=${CLUSTER_NAME}" --wait

kubectl apply -f infrastructure/terraform/eks/karpenter/manifests/provisioning.yaml
kubectl get ec2nodeclass,nodepool
```

**Proving `t3.medium` workload capacity.** No committed workload targets Karpenter capacity: `python-time` has no node selector, and Kafka is pinned to the `system` node group. Pods land on Karpenter nodes only when the system nodes are full. To show a Karpenter launch, schedule pods that the system nodes cannot fit, then check:

```bash
kubectl get nodeclaims -o wide
kubectl get nodes -L karpenter.sh/nodepool,node.kubernetes.io/instance-type
aws ec2 describe-instances --filters "Name=tag:karpenter.sh/nodepool,Values=assessment" \
  --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType,State:State.Name}'
kubectl -n kube-system logs deploy/karpenter --tail=100
```

> Status: the existing evidence notes say live Karpenter `t3.medium` workload-node proof was **not obtained** in the current account. The brief requires this proof ( 2).

#### 5.9 Strimzi Kafka

```bash
bash infrastructure/kubernetes/kafka/install-operator.sh   # Helm OCI chart 1.2.0 into namespace kafka, waits 5m
kubectl apply -f infrastructure/kubernetes/kafka/kafka.yaml   # KafkaNodePool "combined", Kafka "assessment-kafka", KafkaTopic "assessment-events"
kubectl -n kafka wait kafka/assessment-kafka --for=condition=Ready --timeout=600s
kubectl -n kafka get kafka,kafkanodepool,kafkatopic,pods,pvc
```

`deploy-kafka.sh` does the same thing, but first **rewrites** `kafka.yaml` with identical content and runs a server-side dry run. Use either one.

**Interviewer-side message round-trip** (inside the cluster, using the broker pod's bundled Kafka CLI):

```bash
MSG="assessment-$(date +%s)"
kubectl -n kafka exec assessment-kafka-combined-0 -- /opt/kafka/bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 --describe --topic assessment-events
echo "$MSG" | kubectl -n kafka exec -i assessment-kafka-combined-0 -- /opt/kafka/bin/kafka-console-producer.sh \
  --bootstrap-server localhost:9092 --topic assessment-events
kubectl -n kafka exec assessment-kafka-combined-0 -- /opt/kafka/bin/kafka-console-consumer.sh \
  --bootstrap-server localhost:9092 --topic assessment-events --from-beginning --timeout-ms 20000 | grep "$MSG"
```

**Common failures (Phase 5):** see  9 for node readiness, Gateway, Karpenter and Kafka.

**Depends on:** Phase 2. **Required by:** Phase 6 (EKS record) and Phase 8 (cleanup order).

---

### Phase 6 — DNS (Route 53)

**Purpose:** Create the `aws.rahulbagal.tech` hosted zone with alias records for both ALBs.

**Prerequisites:** Phase 2 (EC2 ALB tagged `Name = aws-devops-assessment-ec2-01-app`) and Phase 5.7 (Gateway ALB).

**Before you apply:**

- `ec2-dns.tf` finds the ALB by tag `aws-devops-assessment-ec2-01-app`. If your EC2 `deployment_id` is not `aws-devops-assessment-ec2-01`, edit that tag value.
- `eks-dns.tf` hardcodes the Gateway ALB DNS name and the ALB hosted-zone ID `ZP97RAFLXTNZK` (the ALB zone ID for `ap-south-1`). Replace `alias.name` with `$GATEWAY_ALB`.

```bash
cd infrastructure/terraform/route53
cat > backend.hcl <<EOF
bucket         = "<STATE_BUCKET>"
key            = "route53/terraform.tfstate"
region         = "ap-south-1"
encrypt        = true
dynamodb_table = "<LOCK_TABLE>"
EOF
terraform init -backend-config=backend.hcl
terraform plan -out=route53.tfplan
terraform apply route53.tfplan
terraform output name_servers
cd ../../..
```

**Delegate the subdomain:** at the DNS provider for the parent zone, create an `NS` record for `aws` that lists the four `name_servers`. This step is outside Terraform.

**Verification:**

```bash
dig +short NS aws.rahulbagal.tech
dig +short app.aws.rahulbagal.tech
dig +short eks.aws.rahulbagal.tech
curl -s http://app.aws.rahulbagal.tech/health
curl -s http://eks.aws.rahulbagal.tech/health
```

**Common failures:** `NXDOMAIN` means delegation is missing or still propagating. Compare `dig NS aws.rahulbagal.tech @8.8.8.8` with the Terraform output. `one(...)` error in `data.aws_lb` means the tag look-up matched zero or more than one ALB. A stale EKS alias (the Gateway was recreated) returns no response; update `eks-dns.tf` and re-apply.

**Note:** The route53 provider block has no `allowed_account_ids` guard. Check `aws sts get-caller-identity` first.

---

### Phase 7 — Monitoring

**Purpose:** Two CloudWatch alarms that notify SNS, and Prometheus scraping node and Nginx metrics on the EC2 host.

**Prerequisites:** Phase 2 (alarms and SNS are in the ec2 stack) and Phase 3 (Compose stack running).

**CloudWatch + SNS:** set `monitoring_interviewer_email` in the ec2 `terraform.tfvars` and apply. AWS sends a confirmation email, and **the recipient must click the link**. Until then the subscription stays `PendingConfirmation` and no alarm emails are sent.

```bash
TOPIC=$(terraform -chdir=infrastructure/terraform/ec2 output -raw assessment_alert_topic_arn)
aws sns list-subscriptions-by-topic --topic-arn "$TOPIC" --query 'Subscriptions[].{Endpoint:Endpoint,Arn:SubscriptionArn}'
aws cloudwatch describe-alarms --alarm-name-prefix "$EC2_DEPLOYMENT_ID" \
  --query 'MetricAlarms[].{Name:AlarmName,State:StateValue,Actions:AlarmActions}'
# Optional notification test (changes alarm state temporarily; it reverts on the next evaluation)
aws cloudwatch set-alarm-state --alarm-name "${EC2_DEPLOYMENT_ID}-alb-unhealthy-targets" \
  --state-value ALARM --state-reason "README notification test"
```

**Prometheus:** Compose runs `prometheus` (published only on `127.0.0.1:9090`), `node-exporter` (`--path.rootfs=/host`, host PID, read-only `/` mount) and `nginx-exporter` (scrapes `http://nginx:8080/stub_status`). The scrape configuration is **embedded** in `docker-compose.yml` under `configs.prometheus_config` because the SSM artifact extractor accepts only the exact file list in `scripts/deploy/artifact.py`. `monitoring/prometheus.yml` is a reference copy and is not deployed.

Prometheus is not reachable through the ALB. Check `/targets` through SSM:

```bash
CMD=$(aws ssm send-command --instance-ids "$INSTANCE_ID" --document-name AWS-RunShellScript \
  --parameters '{"commands":["curl -s http://127.0.0.1:9090/api/v1/targets"]}' \
  --query Command.CommandId --output text)
sleep 5
aws ssm get-command-invocation --command-id "$CMD" --instance-id "$INSTANCE_ID" \
  --query StandardOutputContent --output text \
  | python3 -c 'import json,sys; [print(t["labels"]["job"], t["health"], repr(t["lastError"])) for t in json.load(sys.stdin)["data"]["activeTargets"]]'
# Expected:
# node_exporter up ''
# nginx_exporter up ''

# Or open the UI locally (requires the Session Manager plugin):
aws ssm start-session --target "$INSTANCE_ID" --document-name AWS-StartPortForwardingSession \
  --parameters '{"portNumber":["9090"],"localPortNumber":["9090"]}'
# then browse http://localhost:9090/targets
```

---

### Phase 8 — Automated teardown (EventBridge Scheduler → CodeBuild)

> [!CAUTION]
> In its current state the automatic path is **not a working end-to-end destroy**. Read the gaps listed at the end of this phase. The safe default is `TEARDOWN_ENABLED = false` and `EXECUTION_MODE = "PREFLIGHT_ONLY"`. Do not assume the scheduler is enabled. Use the manual procedure in  10 for actual cleanup.

**Purpose:** At `DEPLOYMENT_STARTED_AT + TTL_HOURS`, start a CodeBuild project that removes Kubernetes-created AWS resources first and then destroys the EKS and EC2 stacks.

**Pattern chosen:** EventBridge Scheduler → CodeBuild directly (brief  6, option 2). CodeBuild provides Terraform and a shell. A Lambda cannot easily run the `terraform` binary. The repository has **no Lambda** for adjusting the schedule; changes are made through Terraform variables.

**Prerequisites:** Phase 1 (bucket/table, CodeCommit), a commit **pushed to CodeCommit** whose full SHA becomes `SOURCE_COMMIT_SHA`, and Phases 2/5 for the identifiers.

**Commands:**

```bash
cd infrastructure/terraform/teardown
cp terraform.tfvars.example terraform.tfvars
cp backend.hcl.example backend.hcl     # key = "teardown/terraform.tfstate", region = "ap-south-1"
# Minimum: DEPLOYMENT_STARTED_AT (fixed UTC, e.g. 2026-10-13T09:00:00Z), AWS_ACCOUNT_ID,
#          DEPLOYMENT_ID (= EC2 deployment_id), SOURCE_COMMIT_SHA (40 hex, present on codecommit),
#          BACKEND_BUCKET, LOCK_TABLE, EC2_INSTANCE_ID.
# If EKS_CLUSTER_NAME is set, ALSO set EKS_VPC_ID, EKS_PRIVATE_SUBNET_IDS, EKS_KUBERNETES_VERSION,
#          EKS_CLUSTER_PUBLIC_ACCESS_CIDRS, EKS_NODE_INSTANCE_TYPE, EKS_NODE_DESIRED_SIZE,
#          or the plan fails ("environment_variable.N.value is required").
terraform init -backend-config=backend.hcl
terraform plan -out=teardown.tfplan
terraform apply teardown.tfplan
terraform output
cd ../../..
```

**What gets created:** schedule group and schedule named `<DEPLOYMENT_ID>` (`at(<start+TTL>)`, UTC, state `ENABLED` only if `TEARDOWN_ENABLED`, 3 retries within 1 hour), a Scheduler role allowed only `codebuild:StartBuild` on `<DEPLOYMENT_ID>-destroy`, CodeBuild project `<DEPLOYMENT_ID>-destroy` (source = CodeCommit at `SOURCE_COMMIT_SHA`, buildspec `scripts/cleanup/buildspec.yml`, 30-minute timeout), and a destroy role with **read-only** preflight permissions.

**TTL — change, extend, cancel:**

| Action | How |
| --- | --- |
| Change TTL | `terraform plan -var TTL_HOURS=72 -out=t.tfplan && terraform apply t.tfplan` (whole hours > 0). Deadline = fixed `DEPLOYMENT_STARTED_AT` + TTL |
| Extend | Increase `TTL_HOURS`. Do **not** change `DEPLOYMENT_STARTED_AT` or `DEPLOYMENT_ID` |
| Cancel | `terraform plan -var TEARDOWN_ENABLED=false -out=t.tfplan && terraform apply t.tfplan` sets the schedule to `DISABLED` and deletes no workloads |
| Guard | An enabled schedule whose deadline has already passed is rejected at plan and apply time (preconditions in `schedule.tf`/`target.tf`) |

```bash
aws scheduler get-schedule --name "$EC2_DEPLOYMENT_ID" --group-name "$EC2_DEPLOYMENT_ID" \
  --query '{State:State,Expression:ScheduleExpression,Target:Target.Input}'
terraform -chdir=infrastructure/terraform/teardown output expiry_time
```

**Execution modes and safety gates** (`scripts/cleanup/codebuild.py`): `PREFLIGHT_ONLY` (default) validates identity, source SHA, Terraform 1.15.8, signed delivery records and current status, and produces destroy **plans** without applying them. `DESTROY_FULL_STACK` additionally requires `TEARDOWN_ENABLED`, `FULL_DESTROY_ENABLED`, `FULL_DESTROY_IAM_READY`, complete EKS inputs, and an authorization record `cleanup/authorizations/<id>.json` with action `DESTROY_FULL_STACK`.

**Destroy sequence in full mode** (`kubernetes.py` → `eks.py` → `ec2.py`):

1. Delete `HTTPRoute python-time-route`, then `Gateway python-time-gateway`. Wait until the Gateway and its ALB (matched by DNS name) are gone.
2. Delete `KafkaTopic assessment-events` and `Kafka assessment-kafka`. Wait. Run `helm uninstall strimzi-kafka-operator`.
3. `terraform plan -destroy` and apply for the eks key.
4. `terraform plan -destroy` and apply for the ec2 key (after the state lineage, resource allow-list and tag checks pass).

**Cleanup records:** the executor needs versioned, hash-pinned JSON objects under `s3://<STATE_BUCKET>/cleanup/{config,inputs,records,authorizations,status}/<DEPLOYMENT_ID>.json`. They are produced by `scripts/cleanup/publish.py` (dry run by default):

```bash
python3 scripts/cleanup/publish.py <retained-config.json> --repository-access <YYYY-MM-DDTHH:MM:SSZ> [--ttl-hours 48]
# Publishing requires --publish --approval <approval.json> --publisher-arn <caller-arn>; it must not run inside CodeBuild.
```

**Manual preflight run:** CodeBuild reads the record references from a `CLEANUP_DELIVERY` environment variable (JSON with `configuration`, `inputs`, `record` → `{bucket,key,version_id,sha256}`). Terraform does not set this variable, so a manual run must pass it:

```bash
aws codebuild start-build --project-name "${EC2_DEPLOYMENT_ID}-destroy" \
  --environment-variables-override "name=CLEANUP_DELIVERY,type=PLAINTEXT,value=<json-from-publish.py>"
aws logs tail "/aws/codebuild/${EC2_DEPLOYMENT_ID}-destroy" --since 1h
```

**Known gaps that block automatic, unattended teardown** (from source inspection, not live execution):

1. `CLEANUP_DELIVERY` is not set on the project and the Scheduler input is only `{"ProjectName": ...}`, so a **scheduled** build exits with *"invalid configuration or command failure"*.
2. The destroy role has only read-only permissions. Full mode needs an exact write policy that is **not in this repository** (`FULL_DESTROY_IAM_READY`).
3. `buildspec.yml` installs only Terraform. It does not install or configure `kubectl`/`helm` or run `aws eks update-kubeconfig`, and the destroy role has no EKS access entry.
4. Karpenter `NodePool`/`NodeClaim`s, the Karpenter and ALB Controller Helm releases, the Karpenter CloudFormation stack, the ALB Controller IAM role, the ECR repository, and the cicd, route53, teardown and bootstrap stacks are **not** handled by the executor.
5. `scripts/cleanup/ec2.py` accepts only an allow-list of EC2 state resources and inputs that **predates** `monitoring_assessment.tf`. A state containing the SNS topic or alarms, or inputs containing `monitoring_interviewer_email`, fails validation.

---

## 7. Application Endpoints

| Name | Configured URL | Paths | Status |
| --- | --- | --- | --- |
| EC2 app (Route 53) | `http://app.aws.rahulbagal.tech` | `/`, `/time`, `/health`, `POST /messages` | **Verified 2026-10-13** by read-only check: `/health` 200, `/time` 200, CSP / X-XSS-Protection / X-Content-Type-Options / X-Frame-Options present |
| EKS app (Route 53) | `http://eks.aws.rahulbagal.tech` | `/`, `/time`, `/health` | **Verified 2026-10-13** by read-only check: `/health` 200, `/time` 200 |
| EC2 ALB | `terraform -chdir=infrastructure/terraform/ec2 output -raw alb_dns_name` | as above | Per deployment |
| Gateway ALB | `kubectl -n python-time get gateway python-time-gateway -o jsonpath='{.status.addresses[0].value}'` | as above | Per deployment |
| Prometheus | `http://127.0.0.1:9090` **on the EC2 host only** | `/targets`, `/api/v1/targets` | SSM only |

These endpoints exist only while the environment is deployed. HTTPS is **not** configured: the ALB and Gateway listen on HTTP :80 only, so HSTS is intentionally omitted.

EC2 API reference (`app/app.js`):

| Method | Path | Response |
| --- | --- | --- |
| GET | `/` | HTML clock. `public/clock.js` polls `/time` every second and writes the value with `textContent` |
| GET | `/time` | `{"timestamp":"<ISO-8601>"}`, `Cache-Control: no-store` |
| GET | `/health` | `{"status":"ok"}` (process liveness, not DB readiness) |
| POST | `/messages` | Body `{"text":"1–200 chars"}` → parameterised `INSERT` + `SELECT` → `201 {"id","text"}`. `400` invalid, `413` > 4 KB, `503` DB error |

---

## 8. Testing and Validation

### Local tests available

| Area | Command | Result on 2026-10-13 (this workstation) |
| --- | --- | --- |
| Express app | `npm ci --prefix app && npm test --prefix app` | 4/4 pass |
| DB initialiser (JS) | `node --test scripts/database/test_initialize.cjs` | 6/6 pass |
| Cleanup executor | `PYTHONPATH=scripts/cleanup python3 -m unittest discover -s scripts/cleanup -p 'test_*.py'` | 76 tests OK |
| Deploy helpers | `PYTHONPATH=scripts/deploy python3 -m unittest discover -s scripts/deploy -p 'test_*.py'` | 15 tests OK |
| Database helpers | `PYTHONPATH=scripts/database python3 -m unittest discover -s scripts/database -p 'test_*.py'` | 17 tests OK |
| Host bootstrap | `PYTHONPATH=scripts/host python3 -m unittest discover -s scripts/host -p 'test_*.py'` | 7 tests OK |
| Legacy preflight | `PYTHONPATH=infrastructure/terraform/teardown/executor python3 -m unittest discover -s infrastructure/terraform/teardown/executor -p 'test_*.py'` | 15 tests OK |
| Terraform format | `terraform fmt -check -recursive infrastructure/terraform` | clean |
| Terraform validate | `terraform -chdir=infrastructure/terraform/<stack> init -backend=false && terraform -chdir=infrastructure/terraform/<stack> validate` | all 6 stacks valid |
| Terraform mock tests (ec2) | `terraform -chdir=infrastructure/terraform/ec2 test` | **11 pass, 2 fail, 5 skipped** (see below) |
| Terraform mock tests (teardown) | `terraform -chdir=infrastructure/terraform/teardown test` | **16 pass, 3 fail, 2 skipped** (see below) |
| Compose render | `PGHOST=x PGDATABASE=assessment PGUSER=x PGPASSWORD=x docker compose config --quiet` | exit 0 |

**Terraform test failures** are stale tests that no longer match the code:

- `ec2/network.tftest.hcl` refers to `aws_vpc_security_group_ingress_rule.ssh`, which was removed when SSH ingress was replaced by SSM.
- `ec2/instances.tftest.hcl` `runtime_reads` expects the runtime policy without the `images/*` prefix.
- `teardown/codebuild.tftest.hcl` expects buildspec `infrastructure/terraform/teardown/executor/buildspec.yml` (the code uses `scripts/cleanup/buildspec.yml`) and six policy statements (the code has nine). `exact_workload_targets` sets `EKS_CLUSTER_NAME` without the other EKS inputs and hits the null-value plan error described in Phase 8.

Other local checks:

```bash
python3 -m py_compile apps/python-time/app.py                     # no Python app unit tests exist
for f in scripts/deploy/*.sh scripts/host/*.sh scripts/cleanup/*.sh infrastructure/kubernetes/kafka/*.sh; do bash -n "$f"; done
docker build --platform linux/amd64 -t assessment-app:local ./app
docker build --platform linux/amd64 -t python-time:local apps/python-time
```

`scripts/database/run_integration.py` is an optional Docker integration harness (TLS PostgreSQL + Nginx headers + upstream-failure behaviour). It expects existing local containers `assessment-review-app-1` and `assessment-review-nginx-1`, which a fresh clone does not have.

### Running the EC2 stack locally

```bash
cp .env.example .env                 # set PG* to a reachable PostgreSQL; for a local non-TLS DB use PGSSLMODE=disable
mkdir -p certs                       # put rds-ca.pem here when PGSSLMODE=verify-full
docker compose up -d --build
curl -s localhost/health; curl -sI localhost/ | grep -i x-frame
docker compose down
```

### Kubernetes and infrastructure health checks

```bash
kubectl get nodes; kubectl get pods -A | grep -v Running
kubectl -n python-time get deploy,svc,gateway,httproute
kubectl -n kafka get kafka,kafkatopic,pods,pvc
aws elbv2 describe-target-health --target-group-arn "$(terraform -chdir=infrastructure/terraform/ec2 output -raw target_group_arn)"
aws cloudwatch describe-alarms --alarm-name-prefix "$EC2_DEPLOYMENT_ID" --query 'MetricAlarms[].[AlarmName,StateValue]'
```

---

## 9. Troubleshooting

| Area | Diagnostic | How to read the result |
| --- | --- | --- |
| **Terraform backend init** | `terraform init -reconfigure -backend-config=backend.hcl` | `NoSuchBucket`: wrong bucket or Phase 1 not done. `AccessDenied`: credentials/account. A deprecation warning about `dynamodb_table` is expected on newer Terraform; locking still uses the table |
| **State lock** | `aws dynamodb scan --table-name "$LOCK_TABLE" --projection-expression LockID` | A stale lock after a crashed run: confirm that no other run is active, then `terraform force-unlock <LOCK_ID>` |
| **IAM / account** | `aws sts get-caller-identity`; `terraform plan` error text | `allowed_account_ids` error: wrong account. `UnauthorizedOperation` with an encoded message: `aws sts decode-authorization-message --encoded-message <msg>` |
| **CodeBuild** | `aws codebuild batch-get-builds --ids <id> --query 'builds[0].phases'`; `aws logs tail /aws/codebuild/<project>` | The failing phase shows where it broke: `PRE_BUILD` = tests, `BUILD` = Docker/S3/SSM |
| **SSM command** | `aws ssm list-command-invocations --instance-id "$INSTANCE_ID" --details --max-items 3` | `Undeliverable`: agent offline. `Failed` + *"details withheld"*: inspect the host as shown below |
| **Host inspection** | `aws ssm start-session --target "$INSTANCE_ID"`, then `sudo docker ps -a`, `sudo docker compose ls`, `sudo ls -l /opt/assessment /opt/assessment/current`, `sudo docker logs assessment-app-app-1 --tail 50` | Unhealthy `app` usually means DB connectivity or the `app.env` contents. `nginx` waits for a healthy `app` |
| **ALB health** | `aws elbv2 describe-target-health --target-group-arn <arn>` | `Target.ResponseCodeMismatch`: Nginx up, app failing. `Target.Timeout`: Compose down or SG issue |
| **RDS connectivity** | From the host: `sudo docker exec assessment-app-app-1 node -e "require('net').connect(5432,'<db-host>').on('connect',()=>{console.log('ok');process.exit()})"` | Timeout: SG/subnet route. `ok` but app 503: credentials, CA (`PGSSLROOTCERT=/certs/rds-ca.pem`) or role grants |
| **Docker Compose** | `docker compose config` | `required variable PGHOST is missing`: `.env` not supplied. On the host, the env file is `/opt/assessment/runtime/app.env` |
| **EKS node readiness** | `kubectl get nodes`; `aws eks describe-nodegroup --cluster-name "$CLUSTER_NAME" --nodegroup-name system --query nodegroup.health` | `NodeCreationFailure`: subnet NAT route, IAM policies or quota |
| **kubectl access** | `aws eks describe-cluster --name "$CLUSTER_NAME" --query 'cluster.resourcesVpcConfig.publicAccessCidrs'` | Timeouts: your IP is not in the list. `Unauthorized`: no access entry for your principal |
| **Gateway API routing** | `kubectl -n python-time describe gateway python-time-gateway`; `kubectl -n kube-system logs deploy/aws-load-balancer-controller --tail=100` | No `Programmed=True`: missing CRDs, `ALBGatewayAPI` feature gate, or controller IAM. Target group unhealthy: pods not Ready or `/health` failing |
| **Kafka** | `kubectl -n kafka get kafka assessment-kafka -o jsonpath='{.status.conditions}'`; `kubectl -n kafka get pvc`; `kubectl -n kafka logs deploy/strimzi-cluster-operator --tail=100` | PVC `Pending`: `gp3` StorageClass or EBS CSI add-on missing. Broker `Pending`: system nodes lack the 512Mi request |
| **Karpenter** | `kubectl get nodepool assessment -o yaml`; `kubectl get nodeclaims`; `kubectl -n kube-system logs deploy/karpenter --tail=100` | `UnauthorizedOperation`: CloudFormation policies or Pod Identity missing. NodeClaim launched but node never joins: missing `EC2_LINUX` access entry for `KarpenterNodeRole-<cluster>` |
| **DNS** | `dig +trace app.aws.rahulbagal.tech` | Trace stops at the parent zone: NS delegation is missing |
| **SNS** | `aws sns list-subscriptions-by-topic --topic-arn "$TOPIC"` | `PendingConfirmation`: the recipient has not confirmed |
| **Teardown** | `aws logs tail /aws/codebuild/<id>-destroy`; `aws scheduler get-schedule ...` | *"Cleanup build stopped: …"* gives the failed gate. *"invalid configuration or command failure"* on a scheduled run usually means `CLEANUP_DELIVERY` is absent (Phase 8 gap 1) |
| **Destroy hangs on VPC/subnet** | `aws ec2 describe-network-interfaces --filters Name=vpc-id,Values=<vpc> --query 'NetworkInterfaces[].{Id:NetworkInterfaceId,Desc:Description}'` | Remaining `ELB app/k8s-…` or EKS/Karpenter ENIs: delete the Gateway / Karpenter nodes / EKS stack first |

---

## 10. Cleanup and Cost Management

### Intended 48-hour behaviour

`TTL_HOURS` (default `48`) sets the one-time Scheduler deadline relative to the fixed `DEPLOYMENT_STARTED_AT`. The schedule exists **disabled** unless `TEARDOWN_ENABLED = true`. Even when it is enabled, the gaps in Phase 8 mean the build would stop without destroying anything. **Plan to clean up manually.**

### Manual cleanup procedure (destructive)

> [!CAUTION]
> These commands permanently delete infrastructure and data. RDS has no final snapshot and no backups. The artifact bucket is force-destroyed. Run each `terraform plan -destroy` and review it before applying. Order matters: Kubernetes-created resources → EKS → out-of-band EKS dependencies → cicd/route53/teardown → EC2 → bootstrap.

```bash
# 0. Stop new deployments and the scheduler
terraform -chdir=infrastructure/terraform/teardown apply -var TEARDOWN_ENABLED=false   # or destroy it in step 5

# 1. Kubernetes resources that own AWS resources
kubectl -n python-time delete httproute python-time-route --wait
kubectl -n python-time delete gateway python-time-gateway --wait
aws elbv2 describe-load-balancers --query 'LoadBalancers[?starts_with(LoadBalancerName,`k8s-`)].LoadBalancerName'   # wait until empty
kubectl -n kafka delete kafkatopic assessment-events --wait
kubectl -n kafka delete kafka assessment-kafka --wait
kubectl -n kafka delete kafkanodepool combined --wait            # PVC removed (deleteClaim: true)
helm uninstall strimzi-kafka-operator -n kafka --wait
kubectl delete nodepool assessment && kubectl delete ec2nodeclass assessment
kubectl get nodeclaims                                          # wait until empty (Karpenter terminates its EC2)
helm uninstall karpenter -n kube-system --wait
helm uninstall aws-load-balancer-controller -n kube-system --wait

# 2. EKS stack (same tfvars as apply)
terraform -chdir=infrastructure/terraform/eks plan -destroy -out=eks-destroy.tfplan
terraform -chdir=infrastructure/terraform/eks apply eks-destroy.tfplan

# 3. Out-of-band EKS dependencies
aws cloudformation delete-stack --stack-name "Karpenter-${CLUSTER_NAME}"
aws iam detach-role-policy --role-name "${CLUSTER_NAME}-alb-controller" --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/${CLUSTER_NAME}-alb-controller"
aws iam delete-role --role-name "${CLUSTER_NAME}-alb-controller"
aws iam delete-policy --policy-arn "arn:aws:iam::${ACCOUNT_ID}:policy/${CLUSTER_NAME}-alb-controller"
aws ecr delete-repository --repository-name eks-python-time --force

# 4. DNS and CI/CD (cicd reads ec2 state, so destroy it before ec2)
terraform -chdir=infrastructure/terraform/route53 destroy
terraform -chdir=infrastructure/terraform/cicd destroy

# 5. Teardown stack
terraform -chdir=infrastructure/terraform/teardown destroy

# 6. EC2 stack (VPC, NAT, ALB, EC2, RDS, artifact bucket, secrets, SNS, alarms)
terraform -chdir=infrastructure/terraform/ec2 plan -destroy -out=ec2-destroy.tfplan
terraform -chdir=infrastructure/terraform/ec2 apply ec2-destroy.tfplan

# 7. Leftover check
aws ec2 describe-instances --filters Name=tag:Project,Values=aws-devops-practical-assessment Name=instance-state-name,Values=running,pending
aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerName'
aws rds describe-db-instances --query 'DBInstances[].DBInstanceIdentifier'
aws eks list-clusters
aws logs describe-log-groups --log-group-name-prefix /aws/codebuild/
```

**Bootstrap (last; optional).** The state bucket has `force_destroy = false` and versioning enabled, and it holds the bootstrap state itself. To remove it: migrate bootstrap state back to local (`mv backend.tf backend.tf.disabled && terraform init -migrate-state`), empty **all object versions** in the bucket, then run `terraform destroy`. This also deletes the CodeCommit repository and the lock table.

### What is retained vs destroyed

| Item | On stack destroy |
| --- | --- |
| RDS data | Deleted. No final snapshot, no automated backups |
| Artifact bucket | Deleted with all versions (`force_destroy = true`) |
| Application secret | Deleted immediately (`recovery_window_in_days = 0`). The RDS-managed master secret goes with the DB |
| CodeBuild log groups | Deleted with their stacks (7-day retention) |
| Terraform state bucket, lock table, CodeCommit | **Retained** until bootstrap is destroyed |
| Karpenter CFN stack, ALB Controller IAM, ECR repo, EKS access entries | **Retained** unless removed manually (step 3) |

### Cost drivers

There are no verified cost figures in this repository. Ongoing charges come from: NAT gateway (hourly + data), 2 ALBs, EC2 `t3.small`, RDS `db.t4g.micro` + 20 GB gp3, the EKS control plane, 2× `t3.medium` system nodes plus any Karpenter `t3.medium` nodes, the EBS volume for the Kafka PVC, public IPv4 addresses, the Route 53 hosted zone, CodeBuild minutes, CloudWatch Logs and S3/DynamoDB (small). Use the AWS Pricing Calculator for `ap-south-1` before deploying, and destroy promptly.

---

## 11. Security Considerations

What the code implements:

- **No SSH:** no port-22 ingress rule exists. Access is through SSM Session Manager (`AmazonSSMManagedInstanceCore`). `reviewer_ssh_cidr` is validated (/24–/32) but unused.
- **Network boundaries:** the ALB SG is the only internet-facing SG (port 80). EC2 accepts port 80 only from the ALB SG. RDS accepts 5432 only from the EC2 SG and is `publicly_accessible = false` in private subnets. Prometheus binds to `127.0.0.1`. Nginx `stub_status` is on an unpublished port with an IP allow-list. The EKS public endpoint is restricted to `cluster_public_access_cidrs`, and `0.0.0.0/0` is rejected by validation.
- **Secrets:** the RDS master password is managed by RDS in Secrets Manager. The application password is generated locally by `populate_secret.py` and sent to Secrets Manager over stdin, not in arguments, files or Terraform state. The runtime env file on the host is root-owned with mode 0600. No secret values appear in tfvars examples.
- **Encryption:** S3 state and artifact buckets use SSE-S3 and deny non-TLS requests. DynamoDB has SSE. RDS storage is encrypted, and the app connects with `PGSSLMODE=verify-full` against a checksum-pinned RDS CA bundle. The EC2 root volume is encrypted. The Karpenter SQS queue uses SSE and denies non-TLS.
- **Instance hardening:** IMDSv2 required with hop limit 1. App containers run as non-root (`node`, uid 10001 for Python).
- **Supply chain:** deployments use full commit SHAs, S3 object version IDs and SHA-256 checks. Docker Compose and Terraform binaries are SHA-256 verified. The SSM document installs helpers only after a hash check. Container images are version-tagged but **not digest-pinned**.
- **IAM scope:** CodeBuild, the EC2 runtime role, the Scheduler and the destroy role are scoped to specific ARNs and use `aws:SourceArn`/`aws:SourceAccount` conditions on trust policies. Exceptions: `ssm:GetCommandInvocation` and `elasticloadbalancing:DescribeLoadBalancers` use `*`, the vendor ALB Controller policy and Karpenter template contain AWS-recommended wildcards, and the teardown role falls back to `cluster/*` for `eks:DescribeCluster` when no cluster name is given.
- **Terraform guards:** `allowed_account_ids` and region validation on four of the six stacks (not cicd's region or route53). State is versioned for recovery.
- **Application:** CSP `default-src 'self'` (no `*`), `X-XSS-Protection`, `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` with `always` (headers are also sent on error responses). Parameterised SQL, 200-character limit, 4 KB body limit, JSON-only responses, and DOM updates through `textContent`.

Limitations: HTTP only (no TLS/HSTS), a single NAT and a single-AZ RDS, no WAF, no CloudTrail/GuardDuty configuration in this repository, and an unauthenticated demo `POST /messages`. The Python app's inline script uses `innerText`, and Gunicorn is not behind Nginx, so the EKS path does not set the security headers that the EC2 Nginx sets. This README makes no production-grade or compliance claim.

---

## 12. Assessment Verification Checklist

### A. Implemented in code (reviewable in the repository)

- [x] Terraform for VPC (public + private subnets, IGW, route tables, NAT), EC2, ALB, RDS, S3, Secrets Manager, SSM, CloudWatch alarms, SNS (`infrastructure/terraform/ec2`)
- [x] S3 state + DynamoDB locking, separate keys per stack in one bucket/table (`bootstrap`, `backend.hcl.example`)
- [x] CodeCommit repository (`bootstrap/main.tf`)
- [x] `terraform.tfvars.example` for bootstrap, ec2, eks, teardown. **Missing for cicd and route53**
- [x] `TTL_HOURS` Terraform variable (default 48) with documented change/extend/cancel (Phase 8)
- [x] Dockerfiles, `docker-compose.yml`, Nginx reverse proxy with CSP/XSS/nosniff/frame headers. HSTS omitted (no TLS)
- [x] Input validation and output encoding against reflected/stored XSS (`app/app.js`, `public/clock.js`)
- [x] `buildspec.yml` + CodeBuild + EventBridge CodeCommit trigger + SSM deployment
- [x] Prometheus + node_exporter + nginx-prometheus-exporter in Compose
- [x] EKS cluster + managed system node group via Terraform
- [x] Karpenter `EC2NodeClass` + `NodePool` restricted to `t3.medium` (`eks/karpenter/manifests/provisioning.yaml`)
- [x] Gateway API `GatewayClass`/`Gateway`/`HTTPRoute`, no Ingress (`infrastructure/kubernetes/gateway-api`)
- [x] Python Deployment + Service with real-time `/time` polling (`kubernetes/python-time`, `apps/python-time`)
- [x] Strimzi operator Helm install + KRaft Kafka + KafkaTopic manifests (`infrastructure/kubernetes/kafka`)
- [x] Route 53 zone and records for both apps (`infrastructure/terraform/route53`)
- [x] EventBridge Scheduler → CodeBuild destroy project with ordered Kubernetes → EKS → EC2 cleanup code
- [x] Architecture diagram source + export (`docs/architecture/`)

### B. Requires deployment verification (evidence must come from a live environment)

- [ ] `terraform plan` shows no drift for each stack in the target account
- [ ] ALB target healthy, `/health` and `/time` 200 through `app.` DNS *(read-only check passed 2026-10-13)*
- [ ] RDS write/read through `POST /messages` returns `201`
- [ ] Security headers on 200 and error responses *(headers present on `/` 2026-10-13)*
- [ ] CodeCommit push → CodeBuild `SUCCEEDED` → new SHA running on EC2
- [ ] `HEAD`, `origin/main` and `codecommit/main` SHAs identical
- [ ] Both CloudWatch alarms exist with the SNS action. The SNS subscription is **Confirmed** (not `PendingConfirmation`)
- [ ] Prometheus `/api/v1/targets`: `node_exporter` and `nginx_exporter` `health=up`
- [ ] EKS nodes Ready, kubectl access works for the reviewer principal
- [ ] Gateway `Programmed=True`, HTTPRoute `Accepted`, `eks.` DNS `/health` and `/time` 200 *(read-only check passed 2026-10-13)*
- [ ] Kafka `Ready`, topic exists, produce/consume round-trip shows the unique message
- [ ] Teardown schedule state and `expiry_time` match the intended TTL

---

