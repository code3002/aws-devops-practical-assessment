"""Guarded EKS Terraform destroy executor."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import ec2

STACK = Path(__file__).resolve().parents[2] / "infrastructure" / "terraform" / "eks"
REQUIRED = {
    "EKS_CLUSTER_NAME", "EKS_VPC_ID", "EKS_PRIVATE_SUBNET_IDS",
    "EKS_KUBERNETES_VERSION", "EKS_CLUSTER_PUBLIC_ACCESS_CIDRS",
    "EKS_NODE_INSTANCE_TYPE", "EKS_NODE_DESIRED_SIZE",
}


def _json_list(value, name):
    try:
        result = json.loads(value)
    except (TypeError, json.JSONDecodeError) as error:
        raise ec2.CleanupError(f"Invalid EKS {name}") from error
    if not isinstance(result, list) or not result or any(not isinstance(item, str) for item in result):
        raise ec2.CleanupError(f"Invalid EKS {name}")
    return result


def inputs_from_environment(environment=None):
    environment = os.environ if environment is None else environment
    missing = sorted(name for name in REQUIRED if not environment.get(name))
    if missing:
        raise ec2.CleanupError("Missing explicit EKS destroy inputs: " + ", ".join(missing))
    cluster = environment["EKS_CLUSTER_NAME"]
    vpc_id = environment["EKS_VPC_ID"]
    subnets = _json_list(environment["EKS_PRIVATE_SUBNET_IDS"], "private subnets")
    cidrs = _json_list(environment["EKS_CLUSTER_PUBLIC_ACCESS_CIDRS"], "public access CIDRs")
    version = environment["EKS_KUBERNETES_VERSION"]
    node_type = environment["EKS_NODE_INSTANCE_TYPE"]
    desired = environment["EKS_NODE_DESIRED_SIZE"]
    ec2.check(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", cluster), "Invalid EKS cluster name")
    ec2.check(re.fullmatch(r"vpc-[0-9a-f]{8,17}", vpc_id), "Invalid EKS VPC ID")
    ec2.check(len(subnets) == 2 and len(set(subnets)) == 2 and
              all(re.fullmatch(r"subnet-[0-9a-f]{8,17}", subnet) for subnet in subnets),
              "Exactly two explicit EKS private subnet IDs are required")
    ec2.check(re.fullmatch(r"1[.][0-9]+", version), "Invalid EKS Kubernetes version")
    ec2.check(all(re.fullmatch(r"(?:[0-9]{1,3}[.]){3}[0-9]{1,3}/(?:[0-9]|[12][0-9]|3[0-2])", cidr) and cidr != "0.0.0.0/0" for cidr in cidrs),
              "Restricted EKS public access CIDRs are required")
    ec2.check(re.fullmatch(r"[a-z][a-z0-9.-]{2,30}", node_type), "Invalid EKS node instance type")
    ec2.check(re.fullmatch(r"[1-9][0-9]*", desired), "Invalid EKS node desired size")
    return {
        "aws_region": environment.get("AWS_REGION", "ap-south-1"),
        "expected_account_id": environment.get("EXPECTED_ACCOUNT_ID"),
        "deployment_id": environment.get("DEPLOYMENT_ID"),
        "vpc_id": vpc_id,
        "private_subnet_ids": subnets,
        "kubernetes_version": version,
        "cluster_public_access_cidrs": cidrs,
        "node_instance_type": node_type,
        "node_desired_size": int(desired),
    }


def _command(args):
    result = subprocess.run(args, capture_output=True, text=True,
                            env=os.environ | {"AWS_PAGER": ""}, timeout=3600)
    ec2.check(result.returncode == 0, "EKS Terraform command failed: " + args[0])
    return result.stdout


def cleanup(config, environment=None, execute=False, authorization=None):
    environment = os.environ if environment is None else environment
    mode = environment.get("EXECUTION_MODE", "PREFLIGHT_ONLY")
    ec2.check(mode in {"PREFLIGHT_ONLY", "DESTROY_FULL_STACK"}, "Unsupported execution mode")
    full_destroy = mode == "DESTROY_FULL_STACK"
    ec2.check(type(execute) is bool and execute == full_destroy, "EKS execution mode mismatch")
    inputs = inputs_from_environment(environment)
    if full_destroy:
        ec2.check(environment.get("FULL_DESTROY_IAM_READY") == "true", "Full destroy IAM readiness is not approved")
        ec2.authorize(config, authorization, action="DESTROY_FULL_STACK")

    with tempfile.TemporaryDirectory(prefix="eks-cleanup-") as directory:
        work = Path(directory)
        (work / "backend.hcl").write_text("".join([
            f"bucket = {json.dumps(environment['BACKEND_BUCKET'])}\n",
            f"key = {json.dumps(environment['EKS_STATE_KEY'])}\n",
            f"region = {json.dumps(environment['AWS_REGION'])}\n",
            "encrypt = true\n",
            f"dynamodb_table = {json.dumps(environment['LOCK_TABLE'])}\n",
            f"allowed_account_ids = [{json.dumps(environment['EXPECTED_ACCOUNT_ID'])}]\n",
        ]))
        (work / "inputs.tfvars.json").write_text(json.dumps(inputs))
        tf = ["terraform", "-chdir=" + str(STACK)]
        _command(tf + ["init", "-reconfigure", "-input=false", "-lockfile=readonly",
                       "-backend-config=" + str(work / "backend.hcl")])
        lock = "true" if full_destroy else "false"
        plan = _command(tf + ["plan", "-destroy", "-input=false", f"-lock={lock}",
                              "-lock-timeout=60s", "-var-file=" + str(work / "inputs.tfvars.json"),
                              "-out=" + str(work / "destroy.tfplan")])
        if not full_destroy:
            print("DRY RUN: EKS destroy plan created; no apply is permitted in preflight mode.")
            return plan
        ec2.check(authorization is not None, "Full destroy authorization is required")
        _command(tf + ["apply", "-input=false", "-lock=true", "-lock-timeout=60s",
                       str(work / "destroy.tfplan")])
        return plan