"""Local tests with a fake AWS CLI; no network or real credentials are used."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("preflight.sh")
SHA = "5890ed075b9a04b947ee87102a77da9d41be070b"

class PreflightTests(unittest.TestCase):
    def execute(self, changes=None, failure=""):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "aws"
            fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
failure = os.environ.get('FAKE_FAILURE', '')
if args == ['--version']:
    print('aws-cli/1.0.0' if failure == 'old_cli' else 'aws-cli/2.31.0 Python/3.12.0 Linux')
    sys.exit(0)
operation = tuple(args[:2])
allowed = {('sts','get-caller-identity'), ('s3api','get-bucket-location'), ('s3api','list-objects-v2'), ('s3api','get-object'), ('dynamodb','describe-table')}
if operation not in allowed: sys.exit(99)
if failure == 'denied_listing' and operation == ('s3api','list-objects-v2'): sys.exit(1)
if failure == 'denied_read' and operation == ('s3api','get-object'): sys.exit(1)
if failure == 'denied_table' and operation == ('dynamodb','describe-table'): sys.exit(1)
if operation == ('sts','get-caller-identity'):
    print('999999999999' if failure == 'wrong_account' else '123456789012')
elif operation == ('s3api','get-bucket-location'):
    print('us-east-1' if failure == 'wrong_bucket_region' else 'ap-south-1')
elif operation == ('s3api','list-objects-v2'):
    key = args[args.index('--prefix') + 1]
    stack = key.split('/')[0]
    exists = stack in ('bootstrap','teardown') or bool(os.environ.get('EC2_INSTANCE_ID' if stack == 'ec2' else 'EKS_CLUSTER_NAME'))
    if failure == 'missing_state' and stack == 'bootstrap': exists = False
    if failure == 'missing_workload' and stack == 'ec2': exists = False
    if failure == 'unexpected_workload' and stack == 'ec2': exists = True
    print(json.dumps({'Contents': [{'Key': key}] if exists else []}))
elif operation == ('s3api','get-object'):
    state = {'version': 4, 'lineage': 'test-lineage', 'resources': [], 'outputs': {'secret':'DO_NOT_LOG_TEST_SECRET'}}
    if failure == 'malformed_state': state = {'secret':'DO_NOT_LOG_TEST_SECRET'}
    Path(args[-1]).write_text(json.dumps(state))
    print('{}')
else:
    table = {'TableStatus': 'ACTIVE', 'KeySchema': [{'AttributeName':'LockID','KeyType':'HASH'}], 'AttributeDefinitions':[{'AttributeName':'LockID','AttributeType':'S'}], 'TableArn':'arn:aws:dynamodb:ap-south-1:123456789012:table/test-assessment-locks'}
    if failure == 'wrong_table': table['TableArn'] = 'arn:aws:dynamodb:ap-south-1:999999999999:table/other'
    print(json.dumps({'Table':table}))
""")
            fake.chmod(0o700)
            env = {"PATH": directory + os.pathsep + os.environ["PATH"], "FAKE_FAILURE": failure,
                   "EXPECTED_ACCOUNT_ID": "123456789012", "AWS_REGION": "ap-south-1", "AWS_DEFAULT_REGION": "ap-south-1",
                   "BACKEND_BUCKET": "test-assessment-state", "LOCK_TABLE": "test-assessment-locks",
                   "DEPLOYMENT_ID": "test-teardown", "EXPECTED_SOURCE_COMMIT": SHA,
                   "CODEBUILD_RESOLVED_SOURCE_VERSION": SHA, "EXECUTION_MODE": "PREFLIGHT_ONLY"}
            for stack in ("BOOTSTRAP", "TEARDOWN", "EC2", "EKS"):
                env[stack + "_STATE_KEY"] = stack.lower() + "/terraform.tfstate"
            env.update(changes or {})
            return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=10)

    def test_valid_read_only_preflight(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Destructive execution remains disabled", result.stdout)

    def test_undeployed_stacks_are_skipped(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ec2: intentionally undeployed", result.stdout)
        self.assertIn("eks: intentionally undeployed", result.stdout)
        self.assertNotIn("DO_NOT_LOG_TEST_SECRET", result.stdout + result.stderr)

    def test_read_failures_are_not_absence(self):
        for failure in ("denied_listing", "denied_read", "denied_table"):
            with self.subTest(failure=failure):
                self.assertNotEqual(self.execute(failure=failure).returncode, 0)

    def test_wrong_account_or_backend_identity(self):
        for failure in ("wrong_account", "wrong_bucket_region", "wrong_table"):
            with self.subTest(failure=failure):
                self.assertNotEqual(self.execute(failure=failure).returncode, 0)

    def test_invalid_state_does_not_expose_content(self):
        result = self.execute(failure="malformed_state")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("DO_NOT_LOG_TEST_SECRET", result.stdout + result.stderr)

    def test_deployed_workload_missing_state_rejected(self):
        self.assertNotEqual(self.execute({"EC2_INSTANCE_ID": "i-0123456789abcdef0"}, failure="missing_workload").returncode, 0)

    def test_unexpected_workload_state_rejected(self):
        self.assertNotEqual(self.execute(failure="unexpected_workload").returncode, 0)

    def test_unsupported_cli_rejected(self):
        self.assertNotEqual(self.execute(failure="old_cli").returncode, 0)

    def test_invalid_keys_or_deployment_rejected(self):
        for changes in ({"EC2_STATE_KEY": "bootstrap/terraform.tfstate"}, {"DEPLOYMENT_ID": "*"}, {"AWS_REGION": "us-east-1"}):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.execute(changes).returncode, 0)

    def test_missing_configuration(self):
        self.assertNotEqual(self.execute({"LOCK_TABLE": ""}).returncode, 0)

    def test_source_mismatch(self):
        self.assertNotEqual(self.execute({"CODEBUILD_RESOLVED_SOURCE_VERSION": "0" * 40}).returncode, 0)

    def test_destructive_mode_rejected(self):
        self.assertNotEqual(self.execute({"EXECUTION_MODE": "DESTROY"}).returncode, 0)

    def test_exact_workload_identifiers(self):
        result = self.execute({"EC2_INSTANCE_ID": "i-0123456789abcdef0", "EKS_CLUSTER_NAME": "test-assessment-eks"})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wildcard_workload_identifiers_rejected(self):
        for name in ("EC2_INSTANCE_ID", "EKS_CLUSTER_NAME"):
            with self.subTest(name=name):
                self.assertNotEqual(self.execute({name: "*"}).returncode, 0)

    def test_missing_state_fails_closed(self):
        self.assertNotEqual(self.execute(failure="missing_state").returncode, 0)

if __name__ == "__main__":
    unittest.main()
