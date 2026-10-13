from datetime import datetime, timezone
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("boto3", types.SimpleNamespace(client=None))
import trigger  # noqa: E402

ENV = {"DEADLINE": "2026-10-15T12:00:00Z", "PROJECT_NAME": "test-destroy"}


class FakeCodeBuild:
    def __init__(self):
        self.calls = []

    def start_build(self, **kwargs):
        self.calls.append(kwargs)
        return {"build": {"id": "test-destroy:1"}}


class TriggerTest(unittest.TestCase):
    def run_handler(self, event, now):
        client = FakeCodeBuild()
        with patch.dict(os.environ, ENV):
            return trigger.handler(event, None, client=client, now=now), client

    def test_starts_build_at_deadline(self):
        result, client = self.run_handler({"source": "scheduler"}, datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc))
        self.assertTrue(result["started"])
        self.assertEqual(client.calls[0]["projectName"], "test-destroy")
        overrides = {item["name"]: item["value"] for item in client.calls[0]["environmentVariablesOverride"]}
        self.assertEqual(overrides, {"TRIGGERED_BY": "scheduler", "TEARDOWN_DEADLINE": ENV["DEADLINE"]})

    def test_tolerates_small_early_skew(self):
        result, _ = self.run_handler({}, datetime(2026, 10, 15, 11, 57, tzinfo=timezone.utc))
        self.assertTrue(result["started"])

    def test_refuses_before_deadline(self):
        result, client = self.run_handler({"source": "scheduler"}, datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc))
        self.assertFalse(result["started"])
        self.assertEqual(client.calls, [])

    def test_force_starts_early_and_is_labelled_manual(self):
        result, client = self.run_handler({"force": True}, datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc))
        self.assertTrue(result["started"])
        overrides = {item["name"]: item["value"] for item in client.calls[0]["environmentVariablesOverride"]}
        self.assertEqual(overrides["TRIGGERED_BY"], "manual")

    def test_force_must_be_boolean_true(self):
        result, client = self.run_handler({"force": "yes"}, datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc))
        self.assertFalse(result["started"])
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
