import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch
import populate_secret

ACCOUNT = '123456789012'
ARN = 'arn:aws:secretsmanager:ap-south-1:123456789012:secret:app-test'


class PopulationTests(unittest.TestCase):
    def flow(self, execute=False, existing=False):
        calls = []
        def request(*args, **kwargs):
            calls.append((args, kwargs))
            if args[0] == 'sts': return {'Account': ACCOUNT}
            if args[1] == 'describe-secret': return {'ARN': ARN, 'VersionIdsToStages': {'version': ['AWSCURRENT']} if existing else {}}
            return {}
        output = io.StringIO()
        with patch.object(populate_secret, 'request', side_effect=request), contextlib.redirect_stdout(output):
            populate_secret.populate(ACCOUNT, ARN, execute)
        writes = [call for call in calls if 'put-secret-value' in call[0]]
        if execute and not existing:
            self.assertEqual(len(writes), 1)
            payload = json.loads(writes[0][1]['payload'])
            self.assertEqual(payload['username'], 'assessment_app')
            self.assertGreaterEqual(len(payload['password']), 32)
            self.assertNotIn(payload['password'], ' '.join(writes[0][0]) + output.getvalue())
            self.assertIn('file:///dev/stdin', writes[0][0])
        else: self.assertFalse(writes)

    def test_default_is_read_only(self): self.flow()
    def test_generated_value_only_enters_stdin(self): self.flow(execute=True)
    def test_existing_secret_not_rotated(self): self.flow(execute=True, existing=True)
    def test_existing_versions_without_current_are_not_overwritten(self):
        with patch.object(populate_secret, 'request', side_effect=[
            {'Account': ACCOUNT}, {'ARN': ARN, 'VersionIdsToStages': {'old': ['AWSPREVIOUS']}}
        ]) as request:
            with self.assertRaises(ValueError): populate_secret.populate(ACCOUNT, ARN, True)
            self.assertEqual(request.call_count, 2)
    def test_wrong_account_stops_before_secret(self):
        with patch.object(populate_secret, 'request', return_value={'Account': '999999999999'}) as request:
            with self.assertRaises(ValueError): populate_secret.populate(ACCOUNT, ARN, True)
            self.assertEqual(request.call_count, 1)
    def test_failed_request_withholds_values(self):
        with patch.object(populate_secret.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'secret', 'secret')):
            with self.assertRaises(ValueError) as error: populate_secret.request('unused')
        self.assertNotIn('secret', str(error.exception))


if __name__ == '__main__': unittest.main()
