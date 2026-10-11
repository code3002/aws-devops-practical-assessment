from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ec2
import publish
import record
import test_ec2


class PublisherTests(unittest.TestCase):
    def setUp(self):
        # Synthetic offline values only, never deployment inputs.
        self.now = datetime(2030, 1, 2, tzinfo=timezone.utc)
        self.start = '2030-01-01T00:00:00Z'
        self.directory = tempfile.TemporaryDirectory(); self.addCleanup(self.directory.cleanup)
        self.work = Path(self.directory.name)
        config = test_ec2.fixture()
        values = dict(expected_account_id=config['account'], deployment_id=config['deployment_id'],
                      reviewer_ssh_cidr='192.0.2.1/32', reviewed_ami_id='ami-'+'a'*17, postgres_version='17.11')
        self.inputs = json.dumps(values).encode()
        (self.work/'inputs.json').write_bytes(self.inputs)
        config.update(inputs_file=str(self.work/'inputs.json'), inputs_sha256=record.digest(self.inputs))
        self.path = self.work/'config.json'; self.path.write_text(json.dumps(config))
        self.arn = 'arn:aws:iam::'+config['account']+':user/offline-publisher'

    def clocks(self):
        first = patch.object(publish, 'datetime', wraps=datetime)
        second = patch.object(record, 'datetime', wraps=datetime)
        return first, second

    def prepare(self, start=None, ttl=48):
        first, second = self.clocks()
        with first as a, second as b:
            a.now.return_value = b.now.return_value = self.now
            return publish.prepare(self.path, self.start if start is None else start, ttl)

    def publication(self, failure=None, wrong_identity=False, bad_approval=False, executor=False, read_denied=False, unversioned=False,
                    bad_authorization=False, duplicate_record=False, existing_status=False, canceled_during_upload=False, lost_response=False):
        config, payloads, bundle = self.prepare()
        if bad_authorization:
            payloads['authorization'] = publish.encode(dict(action='OTHER', configuration_sha256='f'*64, expires_at='2030-01-02T01:00:00Z'))
        if duplicate_record:
            payloads['record'] = payloads['record'][:-1] + b', "enabled": true}'
        bundle = record.digest(publish.encode({name: record.digest(data) for name, data in payloads.items()}))
        approval = dict(action='PUBLISH_EC2_TEARDOWN', bundle_sha256='f'*64 if bad_approval else bundle,
                        publisher_arn=self.arn, expires_at='2030-01-02T01:00:00Z')
        approval_path = self.work/'approval.json'; approval_path.write_text(json.dumps(approval))
        self.puts, objects = [], {}
        self.latest_status = {'enabled': False} if existing_status else None
        status_etag = None
        def aws(c, *args):
            nonlocal status_etag
            if args[0] == 'sts': return {'Account': c['account'], 'Arn': 'other' if wrong_identity else self.arn}
            action = args[1]
            if read_denied: raise ec2.CleanupError('AWS read failed')
            if action == 'get-bucket-location': return {'LocationConstraint': c['region']}
            if action == 'get-bucket-versioning': return {'Status': 'Suspended' if unversioned else 'Enabled'}
            if action == 'get-public-access-block':
                return {'PublicAccessBlockConfiguration': dict.fromkeys(['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets'], True)}
            if action == 'get-bucket-policy-status': return {'PolicyStatus': {'IsPublic': False}}
            key = args[args.index('--key')+1]
            if action == 'get-object':
                if key == c['key']: Path(args[-1]).write_text(json.dumps(test_ec2.snapshot(c))); return {}
                version = args[args.index('--version-id')+1]
                Path(args[-1]).write_bytes(objects[(key, version)])
                return {'VersionId': version}
            self.assertEqual(action, 'put-object')
            data = Path(args[args.index('--body')+1]).read_bytes()
            self.assertEqual(args[args.index('--expected-bucket-owner')+1], c['account'])
            self.assertEqual(args[args.index('--server-side-encryption')+1], 'AES256')
            self.puts.append((key, data, args))
            if '/status/' in key:
                if '--if-none-match' in args and self.latest_status is not None:
                    raise ec2.CleanupError('Conditional write rejected')
                if '--if-match' in args:
                    if canceled_during_upload:
                        status_etag = '"canceled"'; self.latest_status = {'enabled': False}
                    if args[args.index('--if-match')+1] != status_etag:
                        raise ec2.CleanupError('Conditional write rejected')
            if failure == len(self.puts): raise ec2.CleanupError('Mock publication failed')
            version = 'offline-v'+str(len(self.puts)); objects[(key,version)] = data
            etag = '"'+record.digest(data)+'"'
            if '/status/' in key:
                self.latest_status = json.loads(data); status_etag = etag
                if lost_response and '--if-match' in args:
                    raise ec2.CleanupError('Response lost')
            return {'VersionId': version, 'ETag': etag}
        first, second = self.clocks()
        with first as a, second as b, patch.object(ec2, 'aws', side_effect=aws), patch.object(ec2, 'source_files'), patch.dict(publish.os.environ, {'CODEBUILD_BUILD_ID': 'offline' if executor else ''}):
            a.now.return_value = b.now.return_value = self.now
            return publish.publish(config, payloads, bundle, approval_path, self.arn)

    def test_dry_run_uses_existing_schema_and_preserves_input_bytes(self):
        with patch.object(ec2, 'aws') as aws:
            config, payloads, bundle = self.prepare()
            aws.assert_not_called()
        self.assertEqual(payloads['inputs'], self.inputs)
        self.assertEqual(config['inputs_file'], 'inputs.tfvars.json')
        self.assertEqual(json.loads(payloads['record'])['deadline'], '2030-01-03T00:00:00Z')
        self.assertEqual(bundle, record.digest(publish.encode({name: record.digest(data) for name,data in payloads.items()})))

    def test_authoritative_timestamp_and_ttl_rejections(self):
        for value in ['', 'bad', '2031-01-01T00:00:00Z']:
            with self.subTest(value=value), self.assertRaises(ec2.CleanupError): self.prepare(start=value)
        for ttl in [0, True, 10**20]:
            with self.subTest(ttl=ttl), self.assertRaises(ec2.CleanupError): self.prepare(ttl=ttl)

    def test_inputs_hash_tampering_rejected(self):
        (self.work/'inputs.json').write_bytes(b'changed')
        with self.assertRaises(ec2.CleanupError): self.prepare()

    def test_complete_publication_commits_status_last(self):
        delivery = self.publication()
        self.assertEqual(set(delivery), {'configuration','inputs','record','authorization'})
        self.assertIn('--if-none-match', self.puts[0][2])
        self.assertIn('--if-match', self.puts[-1][2])
        self.assertTrue(json.loads(self.puts[-1][1])['enabled'])
        for name, source in delivery.items():
            self.assertEqual(source['sha256'], record.digest(self.puts[['configuration','inputs','record','authorization'].index(name)+1][1]))

    def test_partial_upload_failure_never_enables_status(self):
        for stage in range(1,6):
            with self.subTest(stage=stage), self.assertRaises(ec2.CleanupError): self.publication(failure=stage)
            self.assertFalse(any(json.loads(data).get('enabled') is True for key,data,args in self.puts if '/status/' in key))

    def test_approval_and_publisher_identity_required_before_writes(self):
        for arguments in [dict(wrong_identity=True), dict(bad_approval=True), dict(executor=True)]:
            with self.subTest(arguments=arguments), self.assertRaises(ec2.CleanupError): self.publication(**arguments)
            self.assertEqual(self.puts, [])

    def test_final_status_failure_is_reported_not_retried(self):
        with self.assertRaises(ec2.CleanupError): self.publication(failure=6)
        self.assertEqual(len(self.puts), 6)

    def test_access_denial_and_unversioned_bucket_block_all_writes(self):
        for arguments in [dict(read_denied=True), dict(unversioned=True)]:
            with self.subTest(arguments=arguments), self.assertRaises(ec2.CleanupError): self.publication(**arguments)
            self.assertEqual(self.puts, [])

    def test_mismatched_authorization_rejected_before_writes(self):
        with self.assertRaises(ec2.CleanupError): self.publication(bad_authorization=True)
        self.assertEqual(self.puts, [])

    def test_duplicate_record_keys_rejected_before_writes(self):
        with self.assertRaises(ec2.CleanupError): self.publication(duplicate_record=True)
        self.assertEqual(self.puts, [])

    def test_existing_status_blocks_duplicate_publication(self):
        with self.assertRaises(ec2.CleanupError): self.publication(existing_status=True)
        self.assertEqual(len(self.puts), 1)
        self.assertFalse(self.latest_status['enabled'])

    def test_cancellation_during_upload_blocks_final_commit(self):
        with self.assertRaises(ec2.CleanupError): self.publication(canceled_during_upload=True)
        self.assertFalse(self.latest_status['enabled'])

    def test_lost_final_response_reports_uncertain_commit_without_retry(self):
        with self.assertRaisesRegex(ec2.CleanupError, 'inspect latest status'):
            self.publication(lost_response=True)
        self.assertTrue(self.latest_status['enabled'])
        self.assertEqual(len(self.puts), 6)

    def test_pending_attempts_have_distinct_identity(self):
        self.publication(); first = json.loads(self.puts[0][1])['attempt']
        self.publication(); second = json.loads(self.puts[0][1])['attempt']
        self.assertNotEqual(first, second)


if __name__ == '__main__':
    unittest.main()
