"""Ordered automatic teardown (brief §6), run by the CodeBuild destroy project.

For every stack in STACK_ORDER (cicd -> eks-workloads -> eks-addons -> eks ->
route53 -> ec2) it initialises the shared S3/DynamoDB backend, reads the
stack's own `destroy_inputs` output (so no private tfvars are needed), plans the
destroy and, only when EXECUTION_MODE=DESTROY, applies it.

Kubernetes ordering: destroying eks-workloads deletes the HTTPRoute/Gateway
(the AWS Load Balancer Controller removes its ALB and target groups), the
NodePool/EC2NodeClass (Karpenter terminates its EC2 nodes) and Kafka (PVC/EBS)
while both controllers still run. Tag-scoped sweeps then remove anything the
controllers left behind before the cluster and the shared VPC are destroyed, so
the VPC destroy cannot hang on dangling ENIs.

PREFLIGHT_ONLY never changes anything: it checks identity and plans each destroy
(Kubernetes stacks only when this executor can already reach the cluster API).
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
TF_ROOT = ROOT / "infrastructure" / "terraform"
KUBERNETES_STACKS = {"eks-workloads", "eks-addons"}
KNOWN_STACKS = ["cicd", "eks-workloads", "eks-addons", "eks", "route53", "ec2"]


class TeardownError(RuntimeError):
    pass


def check(condition, message):
    if not condition:
        raise TeardownError(message)


def log(message):
    print(f"[teardown] {message}", flush=True)


class Runner:
    """Thin subprocess wrapper; tests replace it with a fake."""

    def __call__(self, args, check_result=True, echo=False):
        env = os.environ | {"AWS_PAGER": "", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}
        result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=5400)
        if echo:
            print(result.stdout, end="", flush=True)
            print(result.stderr, end="", file=sys.stderr, flush=True)
        if check_result and result.returncode != 0:
            # stderr from terraform/aws CLI is safe to show; outputs are never echoed.
            raise TeardownError(f"command failed ({result.returncode}): {' '.join(args[:4])}\n{result.stderr[-4000:]}")
        return result

    def sleep(self, seconds):
        time.sleep(seconds)

    def public_ip(self):
        with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=15) as response:
            return response.read().decode().strip()


def aws(run, *args):
    output = run(["aws", "--region", os.environ.get("AWS_REGION", "ap-south-1"), "--output", "json", *args]).stdout
    return json.loads(output) if output.strip() else {}


# --- Terraform ---------------------------------------------------------------
def state_exists(run, bucket, key):
    result = run(["aws", "s3api", "head-object", "--bucket", bucket, "--key", key], check_result=False)
    return result.returncode == 0


def terraform(run, stack, *args, echo=False):
    return run(["terraform", f"-chdir={TF_ROOT / stack}", *args, "-no-color"], echo=echo)


def init(run, stack, bucket, key, table, account):
    with tempfile.NamedTemporaryFile("w", suffix=".hcl", delete=False) as handle:
        handle.write(f'bucket = "{bucket}"\nkey = "{key}"\nregion = "ap-south-1"\nencrypt = true\n'
                     f'dynamodb_table = "{table}"\nallowed_account_ids = ["{account}"]\n')
        backend = handle.name
    terraform(run, stack, "init", "-reconfigure", "-input=false", f"-backend-config={backend}")


def managed_resources(run, stack):
    return [line for line in terraform(run, stack, "state", "list").stdout.splitlines()
            if line and not line.startswith("data.")]


def outputs(run, stack):
    return {name: value["value"] for name, value in json.loads(terraform(run, stack, "output", "-json").stdout or "{}").items()}


def variable_names(stack):
    names = set()
    for path in (TF_ROOT / stack).glob("*.tf"):
        names |= set(re.findall(r'^variable "([^"]+)"', path.read_text(), flags=re.M))
    return names


def write_inputs(stack, inputs, directory):
    values = dict(inputs)
    if "adopt_existing_resources" in variable_names(stack):
        values["adopt_existing_resources"] = False  # import blocks are irrelevant to a destroy
    path = Path(directory) / f"{stack}.tfvars.json"
    path.write_text(json.dumps(values))
    path.chmod(0o600)
    return path


def plan_destroy(run, stack, var_file, plan_file):
    terraform(run, stack, "plan", "-destroy", "-input=false", "-lock-timeout=120s",
              f"-var-file={var_file}", f"-out={plan_file}", echo=True)


def apply_plan(run, stack, plan_file):
    terraform(run, stack, "apply", "-input=false", "-lock-timeout=120s", str(plan_file), echo=True)


# --- EKS API access for the executor ------------------------------------------
def cluster_cidrs(run, cluster):
    return aws(run, "eks", "describe-cluster", "--name", cluster)["cluster"]["resourcesVpcConfig"].get("publicAccessCidrs", [])


def executor_can_reach(run, cluster):
    return f"{run.public_ip()}/32" in cluster_cidrs(run, cluster)


def open_cluster_endpoint(run, cluster):
    """The cluster is about to be destroyed; allow this executor's egress IP."""
    own = f"{run.public_ip()}/32"
    cidrs = cluster_cidrs(run, cluster)
    if own in cidrs:
        return
    check(len(cidrs) < 40, "EKS public access CIDR limit reached")
    log(f"adding executor egress {own} to the EKS public endpoint allow-list")
    update = aws(run, "eks", "update-cluster-config", "--name", cluster,
                 "--resources-vpc-config", f"publicAccessCidrs={','.join(cidrs + [own])}")["update"]["id"]
    for _ in range(90):
        status = aws(run, "eks", "describe-update", "--name", cluster, "--update-id", update)["update"]["status"]
        if status == "Successful":
            return
        check(status in {"InProgress", "Pending"}, f"EKS endpoint update {status}")
        run.sleep(10)
    raise TeardownError("EKS endpoint update timed out")


# --- Tag-scoped sweeps ---------------------------------------------------------
def sweep_cluster_resources(run, cluster, execute):
    """Leftovers of the Load Balancer Controller and Karpenter for this cluster."""
    leftovers = []
    balancers = aws(run, "elbv2", "describe-load-balancers").get("LoadBalancers", [])
    arns = [lb["LoadBalancerArn"] for lb in balancers]
    for start in range(0, len(arns), 20):
        for description in aws(run, "elbv2", "describe-tags", "--resource-arns", *arns[start:start + 20]).get("TagDescriptions", []):
            tags = {tag["Key"]: tag["Value"] for tag in description.get("Tags", [])}
            if tags.get("elbv2.k8s.aws/cluster") == cluster:
                leftovers.append(("load balancer", description["ResourceArn"]))
                if execute:
                    run(["aws", "elbv2", "delete-load-balancer", "--load-balancer-arn", description["ResourceArn"]])
    groups = [group["TargetGroupArn"] for group in aws(run, "elbv2", "describe-target-groups").get("TargetGroups", [])]
    for start in range(0, len(groups), 20):
        for description in aws(run, "elbv2", "describe-tags", "--resource-arns", *groups[start:start + 20]).get("TagDescriptions", []):
            tags = {tag["Key"]: tag["Value"] for tag in description.get("Tags", [])}
            if tags.get("elbv2.k8s.aws/cluster") == cluster:
                leftovers.append(("target group", description["ResourceArn"]))
                if execute:
                    run(["aws", "elbv2", "delete-target-group", "--target-group-arn", description["ResourceArn"]], check_result=False)
    reservations = aws(run, "ec2", "describe-instances", "--filters",
                       f"Name=tag:kubernetes.io/cluster/{cluster},Values=owned",
                       "Name=tag-key,Values=karpenter.sh/nodepool",
                       "Name=instance-state-name,Values=pending,running,stopping,stopped").get("Reservations", [])
    instances = [instance["InstanceId"] for reservation in reservations for instance in reservation["Instances"]]
    leftovers += [("karpenter instance", instance) for instance in instances]
    if execute and instances:
        run(["aws", "ec2", "terminate-instances", "--instance-ids", *instances])
        run(["aws", "ec2", "wait", "instance-terminated", "--instance-ids", *instances])
    profiles = aws(run, "iam", "list-instance-profiles-for-role", "--role-name", f"KarpenterNodeRole-{cluster}").get("InstanceProfiles", []) \
        if role_exists(run, f"KarpenterNodeRole-{cluster}") else []
    for profile in profiles:
        leftovers.append(("karpenter instance profile", profile["InstanceProfileName"]))
        if execute:
            run(["aws", "iam", "remove-role-from-instance-profile", "--instance-profile-name", profile["InstanceProfileName"],
                 "--role-name", f"KarpenterNodeRole-{cluster}"])
            run(["aws", "iam", "delete-instance-profile", "--instance-profile-name", profile["InstanceProfileName"]])
    return leftovers


def role_exists(run, name):
    return run(["aws", "iam", "get-role", "--role-name", name], check_result=False).returncode == 0


def sweep_vpc(run, vpc, cluster, execute):
    """ENIs and security groups the controllers created in the shared VPC."""
    leftovers = []
    interfaces = aws(run, "ec2", "describe-network-interfaces", "--filters", f"Name=vpc-id,Values={vpc}",
                     "Name=status,Values=available").get("NetworkInterfaces", [])
    for interface in interfaces:
        description = interface.get("Description", "")
        tags = {tag["Key"]: tag["Value"] for tag in interface.get("TagSet", [])}
        if description.startswith(("aws-K8S-", "ELB app/k8s-")) or tags.get(f"kubernetes.io/cluster/{cluster}") or tags.get("cluster.k8s.amazonaws.com/name") == cluster:
            leftovers.append(("network interface", interface["NetworkInterfaceId"]))
            if execute:
                run(["aws", "ec2", "delete-network-interface", "--network-interface-id", interface["NetworkInterfaceId"]], check_result=False)
    for tag_filter in (f"Name=tag:elbv2.k8s.aws/cluster,Values={cluster}", f"Name=tag-key,Values=kubernetes.io/cluster/{cluster}"):
        for group in aws(run, "ec2", "describe-security-groups", "--filters", f"Name=vpc-id,Values={vpc}", tag_filter).get("SecurityGroups", []):
            leftovers.append(("security group", group["GroupId"]))
            if execute:
                run(["aws", "ec2", "delete-security-group", "--group-id", group["GroupId"]], check_result=False)
    return leftovers


# --- Orchestration ---------------------------------------------------------------
def destroy_stack(run, stack, var_file, directory, execute):
    plan_file = Path(directory) / f"{stack}.tfplan"
    plan_destroy(run, stack, var_file, plan_file)
    if not execute:
        return
    try:
        apply_plan(run, stack, plan_file)
    except TeardownError as error:
        log(f"{stack}: destroy failed once, retrying after 60s ({str(error).splitlines()[0]})")
        run.sleep(60)
        plan_destroy(run, stack, var_file, plan_file)
        apply_plan(run, stack, plan_file)


def process_stack(run, stack, present, key, bucket, table, account, cluster, directory, execute):
    if not present:
        log(f"{stack}: no state object, skipping")
        return
    init(run, stack, bucket, key, table, account)
    if not managed_resources(run, stack):
        log(f"{stack}: state is empty, skipping")
        return
    stack_outputs = outputs(run, stack)
    check("destroy_inputs" in stack_outputs, f"{stack}: destroy_inputs output missing; apply the current code once first")
    var_file = write_inputs(stack, stack_outputs["destroy_inputs"], directory)
    if stack in KUBERNETES_STACKS:
        check(cluster is not None, f"{stack}: EKS cluster name unknown")
        if execute:
            open_cluster_endpoint(run, cluster)
        elif not executor_can_reach(run, cluster):
            log(f"{stack}: preflight cannot reach the EKS API (endpoint restricted); plan skipped")
            return
    log(f"{stack}: {'destroying' if execute else 'planning destroy'}")
    destroy_stack(run, stack, var_file, directory, execute)


def main(run=None, environ=None):
    run = run or Runner()
    environ = os.environ if environ is None else environ
    mode = environ.get("EXECUTION_MODE", "PREFLIGHT_ONLY")
    check(mode in {"PREFLIGHT_ONLY", "DESTROY"}, f"unsupported EXECUTION_MODE {mode}")
    execute = mode == "DESTROY"
    account, bucket, table = environ["EXPECTED_ACCOUNT_ID"], environ["BACKEND_BUCKET"], environ["LOCK_TABLE"]
    check(environ.get("AWS_REGION", "ap-south-1") == "ap-south-1", "teardown runs only in ap-south-1")
    order = json.loads(environ["STACK_ORDER"])
    check([entry["stack"] for entry in order] == KNOWN_STACKS, "unexpected stack order")
    caller = aws(run, "sts", "get-caller-identity")
    check(caller.get("Account") == account, "AWS account mismatch")
    log(f"mode={mode} triggered_by={environ.get('TRIGGERED_BY', 'unknown')} deadline={environ.get('TEARDOWN_DEADLINE', 'n/a')}")

    keys = {entry["stack"]: entry["key"] for entry in order}
    present = {stack: state_exists(run, bucket, key) for stack, key in keys.items()}
    cluster = vpc = None
    if present["eks"]:
        init(run, "eks", bucket, keys["eks"], table, account)
        eks_outputs = outputs(run, "eks")
        cluster, vpc = eks_outputs.get("cluster_name"), eks_outputs.get("reused_vpc_id")
    if vpc is None and present["ec2"]:
        init(run, "ec2", bucket, keys["ec2"], table, account)
        vpc = outputs(run, "ec2").get("vpc_id")

    leftovers = []
    with tempfile.TemporaryDirectory(prefix="teardown-") as directory:
        for stack in KNOWN_STACKS:
            process_stack(run, stack, present[stack], keys[stack], bucket, table, account, cluster, directory, execute)
            # Sweeps run at their position even if the stack had no state.
            if stack == "eks-workloads" and cluster:
                found = sweep_cluster_resources(run, cluster, execute)
                leftovers += found
                log(f"cluster sweep: {len(found)} controller-created resource(s) {'removed' if execute else 'found'}")
            if stack == "eks" and cluster and vpc:
                found = sweep_vpc(run, vpc, cluster, execute)
                leftovers += found
                log(f"VPC sweep: {len(found)} leftover ENI/security group(s) {'removed' if execute else 'found'}")
    for kind, identifier in leftovers:
        log(f"swept {kind}: {identifier}")
    log("teardown complete" if execute else "preflight complete; nothing was changed")


if __name__ == "__main__":
    os.umask(0o077)
    try:
        main()
    except (TeardownError, KeyError, ValueError) as error:
        raise SystemExit(f"[teardown] stopped: {error}")
