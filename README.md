# AWS DevOps Practical Assessment

This repository implements the assessment as two independent runtime paths:

- EC2 path: Node.js 24 + Express, PostgreSQL RDS, Docker Compose and Nginx.
- EKS path: Python time application, Gateway API, AWS Load Balancer Controller and Strimzi Kafka.

## Architecture

The EC2 path places an internet-facing ALB in front of an EC2 instance. Nginx is the public container and proxies to the Express application. The application connects privately to PostgreSQL RDS. Prometheus, node_exporter and nginx-prometheus-exporter share the Compose network; Prometheus binds only to the EC2 loopback address.

The EKS path uses a Terraform-provisioned cluster and managed system capacity. The AWS Load Balancer Controller provisions an ALB for a Gateway and HTTPRoute. Route 53 points `eks.aws.rahulbagal.tech` to that ALB. The Python application exposes `/`, `/health` and `/time`; the browser polls `/time` once per second. Strimzi manages the Kafka cluster and topic.

The editable architecture diagram is [docs/architecture/aws-assessment-actual-architecture.drawio](docs/architecture/aws-assessment-actual-architecture.drawio). The visible preview is shown below and is also available as [PNG](docs/architecture/aws-assessment-actual-architecture.drawio.png). Open the XML source in diagrams.net to edit or export it.

![AWS DevOps implementation architecture](docs/architecture/aws-assessment-actual-architecture.drawio.png)

## Live URLs

- EC2 application: [http://app.aws.rahulbagal.tech](http://app.aws.rahulbagal.tech)
- EKS Python application: [http://eks.aws.rahulbagal.tech](http://eks.aws.rahulbagal.tech)

## First Principles

The design starts with four independent invariants:

1. **A request needs a public edge and a private data path.** The EC2 ALB is public, Nginx is the only public container, and RDS is reachable only through private networking and security-group references.
2. **A deployment must be immutable.** CodeBuild uses a full commit SHA, packages an exact file list, uploads versioned artifacts, verifies hashes, and asks SSM to deploy that exact identity.
3. **Metrics must originate where the facts exist.** node_exporter reads the host, nginx-exporter reads Nginx status, and Prometheus stores the two scrape results. The public application path is not used as a substitute for infrastructure metrics.
4. **Destruction must remove external controllers before their infrastructure.** Kubernetes-created ALBs, target groups, Kafka resources, and controller-managed ENIs are removed before Terraform destroys EKS and the EC2/VPC path.

The architecture diagram shows the resulting dependencies rather than only the service names. Solid paths represent request or control flow; dashed paths represent state or cleanup dependencies.

## Source And Deployment

GitHub is the primary repository and AWS CodeCommit is the mirror. A CodeCommit update to `main` matches an EventBridge rule, which starts CodeBuild. CodeBuild runs the Node tests, builds the application image, packages the immutable deployment artifact, uploads versioned artifacts, and invokes the EC2 SSM deployment document.

The deployment artifact intentionally embeds the Prometheus configuration in `docker-compose.yml`. This preserves compatibility with the pinned SSM artifact extractor. The artifact is built from a full commit SHA and is integrity-checked before deployment.

### Reproduction From A Clean Checkout

1. Copy each stack's `terraform.tfvars.example` and `backend.hcl.example` to private local inputs.
2. Verify the AWS account, region `ap-south-1`, reviewer CIDR, domain, and budget before applying anything.
3. Apply bootstrap first so the S3 state bucket, DynamoDB lock table, CodeCommit mirror, and cleanup prerequisites exist.
4. Initialize and apply the EC2, CI/CD, EKS, Route 53, and teardown stacks in dependency order.
5. Run the local tests before a meaningful CodeCommit push.
6. Verify the public EC2 ALB, the EKS DNS name, Kafka round-trip, CloudWatch alarms, SNS confirmation, and Prometheus `/targets`.

Terraform is the only provisioning interface. Kubernetes manifests and Helm are used by the EKS installation and cleanup executors after Terraform provisions their required AWS identities and network.

### Failure And Recovery Rules

- **Terraform plan changes an unexpected resource:** stop; do not apply. Refresh state and compare the backend key, account, region, and deployment tags.
- **CodeBuild fails before SSM:** inspect the CodeBuild log, artifact SHA, source SHA, and SSM invocation. The previous immutable artifact remains the rollback target.
- **SSM deployment fails:** do not edit the host manually. Re-run the reviewed artifact or roll back to the previous release through the deployment path.
- **ALB target is unhealthy:** check EC2 SSM health, Docker Compose health, Nginx upstream connectivity, and the application health endpoint in that order.
- **RDS operation fails:** check secret identity, CA checksum, private route, security-group references, and application SQL logs without exposing credentials.
- **Prometheus target is down:** check exporter container status, Compose DNS names, Nginx `stub_status`, and the last scrape error before changing configuration.
- **Gateway is not programmed:** inspect GatewayClass/controller conditions, HTTPRoute acceptance, service endpoints, and ALB Controller logs.
- **Kafka round-trip fails:** inspect Strimzi/Kafka readiness, topic status, broker listener, and consumer offsets; do not recreate the cluster as a first response.
- **Teardown is approaching:** keep `PREFLIGHT_ONLY` until the full-destroy IAM gate and disposable execution evidence are complete. Cancellation is safer than enabling an unverified destroy path.

## Terraform

Each stack has its own backend key while sharing the S3 state bucket and DynamoDB lock table:

- `infrastructure/terraform/bootstrap`
- `infrastructure/terraform/cicd`
- `infrastructure/terraform/ec2`
- `infrastructure/terraform/eks`
- `infrastructure/terraform/route53`
- `infrastructure/terraform/teardown`

Use the corresponding `terraform.tfvars.example` and `backend.hcl.example` files. Never commit `terraform.tfvars`, backend files, state, plans, credentials, or secret values.

## Teardown

The selected pattern is EventBridge Scheduler to CodeBuild. `TTL_HOURS` defaults to 48 and the fixed `DEPLOYMENT_STARTED_AT` value determines the deadline. Cancellation is represented by `TEARDOWN_ENABLED=false`; extension requires a new reviewed start/deadline input rather than silently changing the deployment identity.

The executor is guarded by `PREFLIGHT_ONLY` and `DESTROY_FULL_STACK` modes. In full mode the required sequence is HTTPRoute/Gateway deletion, Gateway ALB disappearance, Kafka topic/cluster/operator cleanup, EKS Terraform destruction, and EC2 Terraform destruction. Full mode also requires explicit EKS inputs, reviewed authorization, and `FULL_DESTROY_IAM_READY=true`. The live environment remains protected until those permissions and disposable teardown evidence are reviewed.

### Teardown Inputs

Use `infrastructure/terraform/teardown/terraform.tfvars.example` as the shape for the private local input file:

- `TTL_HOURS`: positive whole hours, default `48`.
- `DEPLOYMENT_STARTED_AT`: fixed UTC start time; do not recompute during routine plans.
- `TEARDOWN_ENABLED`: `false` cancels the schedule without deleting workloads.
- `EXECUTION_MODE`: `PREFLIGHT_ONLY` by default; `DESTROY_FULL_STACK` only after review.
- `FULL_DESTROY_ENABLED`: explicit second switch for whole-stack destruction.
- `FULL_DESTROY_IAM_READY`: reviewed confirmation that exact destructive permissions are attached.

To extend the deadline, review a new fixed start/deadline input and run a new plan. To cancel, set `TEARDOWN_ENABLED=false` and apply only the Scheduler state change. Never change the deployment identity to extend a live environment.

### Teardown Order

1. Validate the immutable deployment record, source SHA, account, state bucket and DynamoDB lock table.
2. Delete the Python `HTTPRoute` and `Gateway`.
3. Wait for the Gateway-created ALB and target resources to disappear.
4. Delete the Kafka topic and cluster, then uninstall the Strimzi operator.
5. Run the reviewed EKS Terraform destroy plan and apply it only in `DESTROY_FULL_STACK` mode.
6. Run the reviewed EC2 Terraform destroy plan and apply it only after the EKS stage succeeds.
7. Inspect AWS for remaining ALBs, target groups, ENIs, EC2, RDS, EKS and Kafka-owned resources.

Karpenter is included in cleanup ordering when present. The current AWS account does not provide the required live `t3.medium` workload proof, so Karpenter compliance is recorded as an assessment exception.

### Teardown Safety Gates

Full mode requires all of the following:

- `EXECUTION_MODE=DESTROY_FULL_STACK`.
- `TEARDOWN_ENABLED=true`.
- `FULL_DESTROY_ENABLED=true`.
- `FULL_DESTROY_IAM_READY=true` after policy review.
- Explicit EKS cluster, VPC, subnet, Kubernetes version, CIDR and node inputs.
- A current immutable authorization record with action `DESTROY_FULL_STACK`.
- A disposable-environment test with retained logs.

The repository currently proves the ordered cleanup code and preflight behavior. It does not claim the PDF's Section 6 acceptance criterion until disposable full-destroy evidence exists.

## Prometheus Monitoring

Prometheus exists because the assessment requires two different metric sources: host metrics and Nginx metrics. The Compose stack therefore contains three monitoring services:

1. `node-exporter` reads host-level Linux metrics through the read-only `/host` mount and exposes them on the Compose network at port `9100`.
2. `nginx-exporter` calls Nginx `stub_status` on the private Compose-only port `8080` and exposes translated metrics at port `9113`.
3. `prometheus` scrapes `node-exporter:9100` and `nginx-exporter:9113` every 15 seconds.

Prometheus publishes `127.0.0.1:9090` only. It is not exposed through the public ALB. The deployment artifact keeps the configuration inside `docker-compose.yml` because the pinned SSM extractor validates an exact archive file list. This also makes the runtime configuration available on the host without adding another archive member.

The required runtime proof is the Prometheus API response at `/api/v1/targets`: both jobs must have `health=up` and an empty `lastError`. The current live check has passed for both `node_exporter` and `nginx_exporter`. SSM is used for this diagnostic because the Prometheus port is intentionally loopback-only.

## Verification

Local checks include Node tests, cleanup/deployment/database tests, Python compilation, shell syntax, Docker Compose rendering and Terraform validation. Live checks include ALB health, RDS write/read, CodeBuild/SSM deployment, EKS Gateway routing, Python `/health` and `/time`, Kafka produce/consume, DNS, CloudWatch alarms and Prometheus target health.

The latest verified gaps must remain visible to reviewers: SNS email requires confirmation from the recipient, full automatic teardown has not yet been executed in a disposable environment, and the assessment's required Karpenter `t3.medium` workload-node proof is excluded by the current AWS account constraint.

### Requirements And Evidence

| PDF | Requirement and implementation | Evidence/status |
| --- | --- | --- |
| Section 1 | Terraform, containers, CI/CD, monitoring and cleanup | Six Terraform validations, live endpoints and CodeBuild deployment; cleanup execution evidence remains open |
| Section 2 | EKS provisioned with Terraform | Cluster ACTIVE and Ready nodes: verified |
| Section 2 | Karpenter launches workload `t3.medium` | Live proof excluded by the current account constraint: assessment exception |
| Section 2 | Gateway API with Gateway and HTTPRoute | Gateway programmed and HTTPRoute accepted: verified |
| Section 2 | DNS to the Gateway ALB | `eks.aws.rahulbagal.tech` resolves and responds: verified |
| Section 2 | Python date/time application | Public `/health` and `/time`; browser polling implemented: verified |
| Section 2 | Kafka operator, topic and message | Strimzi Ready and produce/consume round-trip: verified |
| Section 3 | GitHub mirrored to CodeCommit | Local, GitHub and CodeCommit `main` SHAs match: verified |
| Section 4 | Dynamic app behind Nginx in Compose | Node tests, Compose rendering and public health/time checks: verified |
| Section 4 | Nginx security headers and input safety | Live header checks, application tests and RDS round-trip: verified |
| Section 5 | VPC, private RDS, EC2 and ALB | Terraform validation, SSM online, ALB healthy and database read/write: verified |
| Section 5 | Route 53 application record | EKS DNS record resolves: verified |
| Section 5 | S3 state and DynamoDB locking | Backend configuration and Terraform validation: implemented; lock evidence remains handoff work |
| Section 5 | CloudWatch alarms and SNS email | CPU/ALB alarms verified; SNS subscription created but recipient confirmation remains open |
| Section 6 | Automatic teardown and 48-hour TTL | Guarded executor and TTL implemented; disposable end-to-end execution remains open |
| Section 7 | CodeCommit push to CodeBuild to EC2 | Latest CodeBuild succeeded for current `main`: verified |
| Section 8 | Prometheus node and Nginx metrics | Remote API shows both targets `up`: verified |
| Section 9 | README and architecture source | This README and the separate draw.io diagram are the reviewer deliverables |

### Verification Commands

```text
npm test --prefix app
PYTHONPATH=scripts/cleanup python3 -m unittest discover -s scripts/cleanup -p 'test_*.py'
PYTHONPATH=scripts/deploy python3 -m unittest discover -s scripts/deploy -p 'test_*.py'
PYTHONPATH=scripts/database python3 -m unittest discover -s scripts/database -p 'test_*.py'
terraform -chdir=infrastructure/terraform/<stack> validate
```

Live checks must be repeated with the current account and region before handoff. Never describe a resource as verified from Terraform configuration alone.

### Design Trade-offs

- Node.js 24 + Express is used for EC2 because the brief permits Node/Express and the deployment contract is Node-based.
- Python/Flask is a separate EKS application because the brief requires Python for that path; the applications are not reused.
- EventBridge Scheduler directly starts CodeBuild because cleanup needs Terraform, kubectl and Helm tooling that do not belong in a Lambda runtime.
- Prometheus binds to EC2 loopback, keeping its UI private while SSM diagnostics inspect `/targets`.
- Prometheus configuration is embedded in Compose instead of added as a new archive member because the pinned SSM extractor validates an exact file list.
- Karpenter live `t3.medium` proof is excluded by the AWS account constraint; this is an assessment exception, not an optional PDF requirement.

## Cost And Safety

The main cost drivers are EC2, RDS, NAT Gateway, ALB, EKS, worker capacity, EBS, CodeBuild minutes and data transfer. Review `terraform plan` before every apply. No destructive teardown, schedule activation or resource creation should be performed without a reviewed plan, explicit approval and a documented rollback or recovery path.
