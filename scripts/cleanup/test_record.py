import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import ec2
import record
from test_ec2 import fixture


class RecordTests(unittest.TestCase):
    def setUp(self):
        # Synthetic offline fixture, never a deployment timestamp or authorization.
        self.now = datetime(2030, 1, 3, tzinfo=timezone.utc)
        self.inputs = b'{}'
        self.config = fixture() | {'inputs_sha256': record.digest(self.inputs)}
        self.data = {
            'version': 1, 'configuration': self.config.copy(),
            'configuration_sha256': record.digest(json.dumps(self.config, sort_keys=True).encode()),
            'inputs_sha256': record.digest(self.inputs),
            'repository_access_granted_at': '2030-01-01T00:00:00Z',
            'TTL_HOURS': 48, 'deadline': '2030-01-03T00:00:00Z',
            'enabled': True, 'retry_hours': 2,
            'authorization': {'action': 'DESTROY_EC2_STACK', 'not_before': '2030-01-03T00:00:00Z',
                              'expires_at': '2030-01-03T02:00:00Z'},
        }

    def validate(self, data=None, now=None, inputs=None):
        with patch.object(record, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now if now is None else now
            return record.validate_record(self.data if data is None else data, self.config,
                                          self.inputs if inputs is None else inputs)

    def test_valid_default_deadline(self):
        self.assertEqual(self.validate(), self.data)

    def test_cancellation_missing_and_extra_fields(self):
        for change in ['cancel', 'missing', 'extra']:
            data = copy.deepcopy(self.data)
            if change == 'cancel': data['enabled'] = False
            elif change == 'missing': del data['repository_access_granted_at']
            else: data['deployment_started_at'] = data['repository_access_granted_at']
            with self.subTest(change=change), self.assertRaises(ec2.CleanupError): self.validate(data)

    def test_wrong_identity_backend_lineage_and_source(self):
        for key in ['account', 'region', 'deployment_id', 'key', 'bucket', 'state_lineage', 'source_sha']:
            data = copy.deepcopy(self.data); data['configuration'][key] = 'unexpected'
            with self.subTest(key=key), self.assertRaises(ec2.CleanupError): self.validate(data)

    def test_hash_tampering(self):
        for key in ['configuration_sha256', 'inputs_sha256']:
            with self.subTest(key=key), self.assertRaises(ec2.CleanupError):
                self.validate(self.data | {key: 'f'*64})
        with self.assertRaises(ec2.CleanupError): self.validate(inputs=b'changed')

    def test_malformed_timestamps_and_deadline(self):
        for value in ['2030-01-01', '2030-02-30T00:00:00Z', '2030-01-01T00:00:00+00:00', None]:
            with self.subTest(value=value), self.assertRaises(ec2.CleanupError):
                self.validate(self.data | {'repository_access_granted_at': value})
        with self.assertRaises(ec2.CleanupError): self.validate(self.data | {'TTL_HOURS': 49})

    def test_exact_not_before_and_exclusive_expiry(self):
        with self.assertRaisesRegex(ec2.CleanupError, 'before'): self.validate(now=self.now-timedelta(seconds=1))
        self.validate(now=self.now+timedelta(hours=2, seconds=-1))
        with self.assertRaisesRegex(ec2.CleanupError, 'expired'): self.validate(now=self.now+timedelta(hours=2))
        with self.assertRaisesRegex(ec2.CleanupError, 'expired'): self.validate(now=self.now+timedelta(days=1))

    def test_invalid_ttl_and_retry_limits(self):
        for key, values in [('TTL_HOURS', [0, -1, True, 48.5, 10**20]), ('retry_hours', [0, 7, True, 2.5])]:
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ec2.CleanupError):
                    self.validate(self.data | {key: value})

    def test_authorization_scope_and_window(self):
        for key, value in [('action', 'OTHER'), ('not_before', '2030-01-02T00:00:00Z'), ('expires_at', '2031-01-03T02:00:00Z')]:
            data = copy.deepcopy(self.data); data['authorization'][key] = value
            with self.subTest(key=key), self.assertRaises(ec2.CleanupError): self.validate(data)

    def load(self, mutation=None, bad_version=False, tamper=False):
        payload = json.dumps(self.data).encode()
        source = dict(bucket=self.config['bucket'], key='cleanup/records/'+self.config['deployment_id']+'.json',
                      version_id='offline-version', sha256=record.digest(payload))
        if mutation: source.update(mutation)
        def aws(config, *args):
            if args[:2] == ('sts', 'get-caller-identity'): return {'Account': config['account']}
            self.assertEqual(args[:2], ('s3api', 'get-object'))
            self.assertEqual(args[args.index('--version-id')+1], 'offline-version')
            self.assertEqual(args[args.index('--expected-bucket-owner')+1], config['account'])
            self.assertEqual(args[args.index('--bucket')+1], source['bucket'])
            self.assertEqual(args[args.index('--key')+1], source['key'])
            Path(args[-1]).write_bytes(payload + (b' ' if tamper else b''))
            return {'VersionId': 'other' if bad_version else 'offline-version'}
        with patch.object(ec2, 'configuration', return_value=(self.config, self.inputs)), patch.object(ec2, 'aws', side_effect=aws), patch.object(record, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now
            return record.load_record(source, 'offline-config')

    def test_versioned_read_only_loading(self):
        self.assertEqual(self.load(), self.data)
        with self.assertRaises(ec2.CleanupError): self.load(bad_version=True)
        with self.assertRaises(ec2.CleanupError): self.load(tamper=True)

    def test_untrusted_or_unversioned_source_rejected(self):
        for mutation in [{'bucket': 'other'}, {'key': 'other'}, {'version_id': 'null'}, {'version_id': ''}, {'sha256': 'bad'}]:
            with self.subTest(mutation=mutation), self.assertRaises(ec2.CleanupError): self.load(mutation)

    def test_duplicate_json_fields_rejected(self):
        with self.assertRaises(ec2.CleanupError):
            json.loads('{"enabled":true,"enabled":false}', object_pairs_hook=record.unique_object)

    def test_configuration_boolean_cannot_be_substituted_with_integer(self):
        data = copy.deepcopy(self.data)
        data['configuration']['never_deployed'] = 0
        with self.assertRaisesRegex(ec2.CleanupError, 'configuration mismatch'): self.validate(data)

    def test_field_types_fail_closed(self):
        for key, value in [('version', True), ('configuration', []), ('configuration_sha256', []),
                           ('inputs_sha256', None), ('enabled', 1), ('authorization', []), ('deadline', 123)]:
            with self.subTest(key=key), self.assertRaises(ec2.CleanupError): self.validate(self.data | {key: value})

    def test_load_errors_are_redacted(self):
        for error in [ValueError('private-value'), OSError('private-value'),
                      ec2.subprocess.TimeoutExpired(['private-value'], 1, output='private-value')]:
            with patch.object(ec2, 'configuration', side_effect=error), self.assertRaises(ec2.CleanupError) as caught:
                record.load_record({}, 'offline-config')
            self.assertNotIn('private-value', str(caught.exception))

    def test_hash_is_verified_before_parsing(self):
        with patch.object(record.json, 'loads', side_effect=AssertionError('Parsed untrusted bytes')):
            with self.assertRaisesRegex(ec2.CleanupError, 'hash mismatch'): self.load(tamper=True)


if __name__ == '__main__':
    unittest.main()
