"""Read-only CodeBuild preflight. No Terraform or AWS mutation commands."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


class PreflightError(ValueError):
    """Safe messages contain only check labels, never state or credentials."""


def check(condition, message):
    if not condition:
        raise PreflightError(message)


def aws(*args):
    result = subprocess.run(["aws", *args], capture_output=True, text=True, timeout=60)
    # AWS stderr may contain unnecessary request details; report only the operation.
    check(result.returncode == 0, "AWS read failed: " + " ".join(args[:2]))
    return result.stdout


def main():
    required = ("EXPECTED_ACCOUNT_ID", "AWS_REGION", "AWS_DEFAULT_REGION", "BACKEND_BUCKET", "LOCK_TABLE",
                "BOOTSTRAP_STATE_KEY", "TEARDOWN_STATE_KEY", "EC2_STATE_KEY", "EKS_STATE_KEY",
                "DEPLOYMENT_ID", "EXPECTED_SOURCE_COMMIT", "EXECUTION_MODE", "CODEBUILD_RESOLVED_SOURCE_VERSION")
    check(all(os.environ.get(name) for name in required), "Missing required configuration")
    env = os.environ
    check(env["EXECUTION_MODE"] == "PREFLIGHT_ONLY", "Destructive execution is unsupported")
    check(env["AWS_REGION"] == env["AWS_DEFAULT_REGION"] == "ap-south-1", "Unexpected region")
    check(re.fullmatch(r"[0-9a-f]{40}", env["EXPECTED_SOURCE_COMMIT"]) and
          env["CODEBUILD_RESOLVED_SOURCE_VERSION"] == env["EXPECTED_SOURCE_COMMIT"], "Source revision mismatch")
    for name, pattern in (("EXPECTED_ACCOUNT_ID", r"[0-9]{12}"),
                          ("BACKEND_BUCKET", r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]"),
                          ("LOCK_TABLE", r"[A-Za-z0-9_.-]{3,255}"),
                          ("DEPLOYMENT_ID", r"[a-z][a-z0-9-]{2,39}")):
        check(re.fullmatch(pattern, env[name]), "Invalid configuration: " + name)
    for name, pattern in (("EC2_INSTANCE_ID", r"i-([0-9a-f]{8}|[0-9a-f]{17})"),
                          ("EKS_CLUSTER_NAME", r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}")):
        if name in env:
            check(re.fullmatch(pattern, env[name]), "Invalid workload identifier")
    keys = {stack: env[stack.upper() + "_STATE_KEY"] for stack in ("bootstrap", "teardown", "ec2", "eks")}
    check(len(set(keys.values())) == 4 and all(re.fullmatch(r"[A-Za-z0-9_-]+/terraform\.tfstate", k)
                                             for k in keys.values()), "Invalid state keys")
    check(sys.version_info >= (3, 9), "Python 3.9 or newer is required")
    cli_version = aws("--version").strip()
    check(re.match(r"aws-cli/2\.[0-9]+\.[0-9]+(?: |$)", cli_version), "AWS CLI v2 is required")
    print(cli_version.split()[0] + "; Python " + sys.version.split()[0])
    print("Terraform, kubectl and Helm are not required or installed by this preflight.")
    account = aws("sts", "get-caller-identity", "--query", "Account", "--output", "text").strip()
    check(account == env["EXPECTED_ACCOUNT_ID"], "AWS account mismatch")
    owner = ("--expected-bucket-owner", env["EXPECTED_ACCOUNT_ID"])
    location = aws("s3api", "get-bucket-location", "--bucket", env["BACKEND_BUCKET"], *owner,
                   "--query", "LocationConstraint", "--output", "text").strip()
    check(location == env["AWS_REGION"], "Backend region mismatch")
    for stack, key in keys.items():
        expected = stack in ("bootstrap", "teardown") or bool(env.get("EC2_INSTANCE_ID" if stack == "ec2" else "EKS_CLUSTER_NAME"))
        listing = json.loads(aws("s3api", "list-objects-v2", "--bucket", env["BACKEND_BUCKET"], *owner,
                                 "--prefix", key, "--output", "json"))
        exists = any(item["Key"] == key for item in listing.get("Contents", []))
        check(exists == expected, "State presence mismatch: " + stack)
        if not expected:
            print(stack + ": intentionally undeployed (state absent)")
            continue
        # Download privately to verify GetObject access, then remove the temporary copy.
        # These are new ephemeral copies, never original state/recovery backups.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.touch(mode=0o600)
            aws("s3api", "get-object", "--bucket", env["BACKEND_BUCKET"], *owner, "--key", key, str(path))
            state = json.loads(path.read_text())
            check(state.get("version") == 4 and isinstance(state.get("resources"), list) and
                  isinstance(state.get("lineage"), str) and bool(state["lineage"]), "Invalid state snapshot: " + stack)
        print(stack + ": state readable; contents withheld")
    table = json.loads(aws("dynamodb", "describe-table", "--table-name", env["LOCK_TABLE"],
                          "--region", env["AWS_REGION"], "--output", "json"))["Table"]
    check(table["TableStatus"] == "ACTIVE" and table["KeySchema"] == [{"AttributeName": "LockID", "KeyType": "HASH"}] and
          {"AttributeName": "LockID", "AttributeType": "S"} in table["AttributeDefinitions"], "Invalid lock table")
    check(table["TableArn"] == "arn:aws:dynamodb:ap-south-1:" + account + ":table/" + env["LOCK_TABLE"], "Lock table identity mismatch")
    print("Read-only source/account/backend preflight passed. Destructive execution remains disabled.")


if __name__ == "__main__":
    try:
        main()
    except PreflightError as error:
        print("Preflight failed: " + str(error), file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        # Fixed message avoids exposing malformed state values or AWS response bodies.
        print("Preflight failed: required configuration, tool, identity or backend check did not pass.", file=sys.stderr)
        sys.exit(1)
