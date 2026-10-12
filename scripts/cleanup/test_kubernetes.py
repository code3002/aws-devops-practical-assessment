import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(__file__))
import kubernetes


class KubernetesCleanupTests(unittest.TestCase):
    def test_preflight_checks_resources_without_delete(self):
        calls = []

        def command(args, input_text=None):
            calls.append(args)
            return '{}'

        with patch.object(kubernetes, 'command', side_effect=command), \
             patch.object(kubernetes, 'cluster_is_active', return_value=True):
            kubernetes.cleanup('ap-south-1', 'assessment-eks', execute=False)

        self.assertEqual(calls, [
            ['kubectl', 'get', 'gateway', 'python-time-gateway', '--namespace', 'python-time', '--output', 'json'],
            ['kubectl', 'get', 'kafka', 'assessment-kafka', '--namespace', 'kafka', '--output', 'json'],
        ])

    def test_invalid_region_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported cleanup region'):
            kubernetes.cleanup('us-east-1', 'assessment-eks', execute=False)

    def test_execute_orders_gateway_before_kafka(self):
        calls = []

        def command(args, input_text=None):
            calls.append(args)
            return '{}'

        with patch.object(kubernetes, 'command', side_effect=command), \
             patch.object(kubernetes, 'cluster_is_active', return_value=True), \
             patch.object(kubernetes, 'resource_exists', return_value=False), \
             patch.object(kubernetes.subprocess, 'run') as run:
            run.return_value.returncode = 1
            kubernetes.cleanup('ap-south-1', 'assessment-eks', execute=True)

        delete_commands = [call for call in calls if call[0:2] == ['kubectl', 'delete']]
        self.assertEqual([call[2] for call in delete_commands], ['httproute', 'gateway', 'kafkatopic', 'kafka'])


if __name__ == '__main__':
    unittest.main()
