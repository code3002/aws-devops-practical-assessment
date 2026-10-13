import json
import subprocess
import unittest

import destroy

ORDER = [{"stack": stack, "key": f"{stack}/terraform.tfstate"} for stack in destroy.KNOWN_STACKS]
ENV = {
    "EXPECTED_ACCOUNT_ID": "123456789012",
    "BACKEND_BUCKET": "state-bucket",
    "LOCK_TABLE": "locks",
    "AWS_REGION": "ap-south-1",
    "STACK_ORDER": json.dumps(ORDER),
}
CLUSTER = "test-eks"


class FakeRunner:
    def __init__(self, missing=(), cidrs=("198.51.100.7/32",), ip="203.0.113.9", account="123456789012",
                 controller_leftovers=False, fail_apply_once=None):
        self.calls = []
        self.missing = set(missing)
        self.cidrs = list(cidrs)
        self.ip = ip
        self.account = account
        self.controller_leftovers = controller_leftovers
        self.fail_apply_once = fail_apply_once
        self.update_polls = 0

    def sleep(self, _seconds):
        pass

    def public_ip(self):
        return self.ip

    def ok(self, payload=""):
        return subprocess.CompletedProcess([], 0, payload if isinstance(payload, str) else json.dumps(payload), "")

    def __call__(self, args, check_result=True, echo=False):
        self.calls.append(list(args))
        if args[0] == "terraform":
            return self.terraform(args)
        return self.aws(args, check_result)

    def terraform(self, args):
        stack = args[1].rsplit("/", 1)[1]
        command = args[2]
        if command == "output":
            values = {"destroy_inputs": {"value": {"expected_account_id": "123456789012"}}}
            if stack == "eks":
                values |= {"cluster_name": {"value": CLUSTER}, "reused_vpc_id": {"value": "vpc-0123456789abcdef0"}}
            if stack == "ec2":
                values |= {"vpc_id": {"value": "vpc-0123456789abcdef0"}}
            return self.ok(values)
        if command == "state":
            return self.ok("aws_vpc.this\ndata.aws_caller_identity.current\n")
        if command == "apply" and self.fail_apply_once == stack:
            self.fail_apply_once = None
            raise destroy.TeardownError("apply failed")
        return self.ok()

    def aws(self, args, check_result):
        joined = " ".join(args)
        if "get-caller-identity" in joined:
            return self.ok({"Account": self.account})
        if "head-object" in joined:
            key = args[args.index("--key") + 1]
            code = 254 if key.split("/")[0] in self.missing else 0
            if code and check_result:
                raise destroy.TeardownError("missing")
            return subprocess.CompletedProcess([], code, "", "")
        if "describe-cluster" in joined:
            return self.ok({"cluster": {"resourcesVpcConfig": {"publicAccessCidrs": self.cidrs}}})
        if "update-cluster-config" in joined:
            return self.ok({"update": {"id": "u-1"}})
        if "describe-update" in joined:
            self.update_polls += 1
            return self.ok({"update": {"status": "InProgress" if self.update_polls < 2 else "Successful"}})
        if "describe-load-balancers" in joined:
            return self.ok({"LoadBalancers": [{"LoadBalancerArn": "arn:lb/k8s"}, {"LoadBalancerArn": "arn:lb/ec2"}]})
        if "describe-target-groups" in joined:
            return self.ok({"TargetGroups": [{"TargetGroupArn": "arn:tg/k8s"}]})
        if "describe-tags" in joined:
            tagged = {"Key": "elbv2.k8s.aws/cluster", "Value": CLUSTER}
            descriptions = []
            for arn in args[args.index("--resource-arns") + 1:]:
                tags = [tagged] if self.controller_leftovers and "k8s" in arn else []
                descriptions.append({"ResourceArn": arn, "Tags": tags})
            return self.ok({"TagDescriptions": descriptions})
        if "describe-instances" in joined:
            instances = [{"InstanceId": "i-0karpenter"}] if self.controller_leftovers else []
            return self.ok({"Reservations": [{"Instances": instances}]})
        if "get-role" in joined:
            return subprocess.CompletedProcess([], 0, "{}", "")
        if "list-instance-profiles-for-role" in joined:
            return self.ok({"InstanceProfiles": []})
        if "describe-network-interfaces" in joined:
            interfaces = [{"NetworkInterfaceId": "eni-k8s", "Description": "aws-K8S-i-0abc", "TagSet": []},
                          {"NetworkInterfaceId": "eni-other", "Description": "RDSNetworkInterface", "TagSet": []}]
            return self.ok({"NetworkInterfaces": interfaces})
        if "describe-security-groups" in joined:
            return self.ok({"SecurityGroups": []})
        return self.ok()

    def commands(self, *words):
        return [call for call in self.calls if all(word in call for word in words)]

    def terraform_calls(self, command):
        return [call[1].rsplit("/", 1)[1] for call in self.calls if call[0] == "terraform" and call[2] == command]


class DestroyTest(unittest.TestCase):
    def run_main(self, runner, **env):
        destroy.main(runner, ENV | env)
        return runner

    def test_preflight_plans_but_never_applies_or_mutates(self):
        runner = self.run_main(FakeRunner(cidrs=["203.0.113.9/32"]), EXECUTION_MODE="PREFLIGHT_ONLY")
        self.assertEqual(runner.terraform_calls("plan"), destroy.KNOWN_STACKS)
        self.assertEqual(runner.terraform_calls("apply"), [])
        mutating = ("update-cluster-config", "delete-load-balancer", "terminate-instances", "delete-network-interface")
        self.assertFalse([call for call in runner.calls if any(word in call for word in mutating)])

    def test_preflight_skips_kubernetes_plans_when_endpoint_is_restricted(self):
        runner = self.run_main(FakeRunner(), EXECUTION_MODE="PREFLIGHT_ONLY")
        self.assertEqual(runner.terraform_calls("plan"), ["cicd", "eks", "route53", "ec2"])
        self.assertFalse(runner.commands("update-cluster-config"))

    def test_destroy_runs_in_dependency_order(self):
        runner = self.run_main(FakeRunner(), EXECUTION_MODE="DESTROY")
        self.assertEqual(runner.terraform_calls("apply"), destroy.KNOWN_STACKS)
        for call in runner.calls:
            if call[0] == "terraform" and call[2] == "plan":
                self.assertIn("-destroy", call)

    def test_destroy_opens_endpoint_before_kubernetes_stacks(self):
        runner = self.run_main(FakeRunner(), EXECUTION_MODE="DESTROY")
        update = runner.commands("update-cluster-config")[0]
        self.assertIn("publicAccessCidrs=198.51.100.7/32,203.0.113.9/32", update)
        first_k8s_plan = next(i for i, call in enumerate(runner.calls) if call[0] == "terraform" and call[2] == "plan" and call[1].endswith("eks-workloads"))
        self.assertLess(runner.calls.index(update), first_k8s_plan)

    def test_sweeps_only_resources_tagged_for_this_cluster(self):
        runner = self.run_main(FakeRunner(controller_leftovers=True), EXECUTION_MODE="DESTROY")
        deleted = [call[call.index("--load-balancer-arn") + 1] for call in runner.commands("delete-load-balancer")]
        self.assertEqual(deleted, ["arn:lb/k8s"])
        self.assertEqual(runner.commands("terminate-instances")[0][-1], "i-0karpenter")
        filters = runner.commands("describe-instances")[0]
        self.assertIn(f"Name=tag:kubernetes.io/cluster/{CLUSTER},Values=owned", filters)
        enis = [call[call.index("--network-interface-id") + 1] for call in runner.commands("delete-network-interface")]
        self.assertEqual(enis, ["eni-k8s"])

    def test_cluster_sweep_precedes_eks_destroy_and_vpc_sweep_precedes_ec2(self):
        runner = self.run_main(FakeRunner(controller_leftovers=True), EXECUTION_MODE="DESTROY")
        index = lambda predicate: next(i for i, call in enumerate(runner.calls) if predicate(call))
        terminate = index(lambda call: "terminate-instances" in call)
        eks_apply = index(lambda call: call[0] == "terraform" and call[2] == "apply" and call[1].endswith("/eks"))
        eni = index(lambda call: "delete-network-interface" in call)
        ec2_apply = index(lambda call: call[0] == "terraform" and call[2] == "apply" and call[1].endswith("/ec2"))
        self.assertLess(terminate, eks_apply)
        self.assertLess(eks_apply, eni)
        self.assertLess(eni, ec2_apply)

    def test_missing_states_are_skipped(self):
        runner = self.run_main(FakeRunner(missing={"eks-workloads", "eks-addons", "eks"}), EXECUTION_MODE="DESTROY")
        self.assertEqual(runner.terraform_calls("apply"), ["cicd", "route53", "ec2"])

    def test_failed_apply_is_retried_once(self):
        runner = self.run_main(FakeRunner(fail_apply_once="ec2"), EXECUTION_MODE="DESTROY")
        self.assertEqual(runner.terraform_calls("apply").count("ec2"), 2)

    def test_account_mismatch_stops_before_terraform(self):
        runner = FakeRunner(account="999999999999")
        with self.assertRaisesRegex(destroy.TeardownError, "account mismatch"):
            destroy.main(runner, ENV | {"EXECUTION_MODE": "DESTROY"})
        self.assertFalse([call for call in runner.calls if call[0] == "terraform"])

    def test_unknown_mode_and_order_are_rejected(self):
        with self.assertRaises(destroy.TeardownError):
            destroy.main(FakeRunner(), ENV | {"EXECUTION_MODE": "NUKE"})
        bad = json.dumps(list(reversed(ORDER)))
        with self.assertRaisesRegex(destroy.TeardownError, "stack order"):
            destroy.main(FakeRunner(), ENV | {"EXECUTION_MODE": "DESTROY", "STACK_ORDER": bad})

    def test_adoption_imports_are_disabled_for_destroy(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            values = json.loads(destroy.write_inputs("eks", {"deployment_id": "x"}, directory).read_text())
            self.assertIs(values["adopt_existing_resources"], False)
            values = json.loads(destroy.write_inputs("ec2", {"deployment_id": "x"}, directory).read_text())
            self.assertNotIn("adopt_existing_resources", values)


if __name__ == "__main__":
    unittest.main()
