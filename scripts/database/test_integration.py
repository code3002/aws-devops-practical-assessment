import subprocess
import unittest
from unittest.mock import patch
import run_integration


class IntegrationHarnessTests(unittest.TestCase):
    def test_failed_command_withholds_sensitive_output(self):
        result = subprocess.CompletedProcess([], 1, 'test-password', 'test-password')
        with patch.object(run_integration.subprocess, 'run', return_value=result):
            with self.assertRaises(RuntimeError) as error:
                run_integration.run(['docker', 'compose', 'up'])
        self.assertNotIn('test-password', str(error.exception))

    def test_cleanup_attempts_every_resource_and_reports_failure(self):
        results = [subprocess.CompletedProcess([], code, '', 'test-password') for code in [1, 0, 0]]
        with patch.object(run_integration.subprocess, 'run', side_effect=results) as command:
            with self.assertRaises(RuntimeError) as error:
                run_integration.cleanup(['docker', 'compose', '-p', 'fixture'], 'fixture', True)
            self.assertEqual(command.call_count, 3)
        self.assertNotIn('test-password', str(error.exception))

    def test_cleanup_success_checks_each_exit_status(self):
        with patch.object(run_integration.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as command:
            run_integration.cleanup(['docker', 'compose'], 'fixture', True)
            self.assertEqual(command.call_count, 3)


if __name__ == '__main__':
    unittest.main()
