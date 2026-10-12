import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import eks
import test_ec2


def environment(mode="PREFLIGHT_ONLY"):
    return {
        "EXECUTION_MODE": mode,
        "FULL_DESTROY_IAM_READY": "true",
        "AWS_REGION": "ap-south-1",
        "EXPECTED_ACCOUNT_ID": "205542837884",
        "DEPLOYMENT_ID": "assessment",
        "BACKEND_BUCKET": "assessment-state",
        "LOCK_TABLE": "assessment-locks",
        "EKS_STATE_KEY": "eks/terraform.tfstate",
        "EKS_CLUSTER_NAME": "assessment-eks",
        "EKS_VPC_ID": "vpc-0123456789abcdef0",
        "EKS_PRIVATE_SUBNET_IDS": json.dumps(["subnet-0123456789abcdef0", "subnet-abcdef0123456789a"]),
        "EKS_KUBERNETES_VERSION": "1.35",
        "EKS_CLUSTER_PUBLIC_ACCESS_CIDRS": json.dumps(["198.51.100.10/32"]),
        "EKS_NODE_INSTANCE_TYPE": "t3.small",
        "EKS_NODE_DESIRED_SIZE": "2",
    }


class EksCleanupTests(unittest.TestCase):
    def test_preflight_creates_plan_but_never_applies(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return type("Result", (), {"returncode": 0, "stdout": "plan"})()

        with patch.object(eks.subprocess, "run", side_effect=run):
            eks.cleanup(test_ec2.fixture(), environment(), execute=False)

        self.assertTrue(any("init" in call for call in calls))
        self.assertTrue(any("plan" in call and "-destroy" in call for call in calls))
        self.assertFalse(any("apply" in call for call in calls))

    def test_full_mode_requires_iam_gate(self):
        env = environment("DESTROY_FULL_STACK") | {"FULL_DESTROY_IAM_READY": "false"}
        with self.assertRaisesRegex(ValueError, "IAM readiness"):
            eks.cleanup(test_ec2.fixture(), env, execute=True, authorization={})

    def test_full_mode_constructs_destroy_plan_then_apply(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return type("Result", (), {"returncode": 0, "stdout": "plan"})()

        with patch.object(eks.subprocess, "run", side_effect=run), \
             patch.object(eks.ec2, "authorize") as authorize:
            eks.cleanup(test_ec2.fixture(), environment("DESTROY_FULL_STACK"),
                        execute=True, authorization={})

        plan = next(call for call in calls if "plan" in call)
        apply = next(call for call in calls if "apply" in call)
        self.assertIn("-destroy", plan)
        self.assertTrue(any(argument.startswith("-var-file=") for argument in plan))
        self.assertEqual(apply[-1].endswith("destroy.tfplan"), True)
        authorize.assert_called_once_with(test_ec2.fixture(), {}, action="DESTROY_FULL_STACK")

    def test_missing_explicit_input_fails_closed(self):
        env = environment()
        del env["EKS_VPC_ID"]
        with self.assertRaisesRegex(ValueError, "EKS_VPC_ID"):
            eks.inputs_from_environment(env)


if __name__ == "__main__":
    unittest.main()