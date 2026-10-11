from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import ec2
import record
import status
import test_record
import test_ec2


class StatusTests(unittest.TestCase):
    def setUp(self):
        fixture = test_record.RecordTests(); fixture.setUp()
        self.config, self.inputs, self.deployment, self.now = fixture.config, fixture.inputs, fixture.data, fixture.now
        self.source = dict(bucket=self.config['bucket'], key='cleanup/records/'+self.config['deployment_id']+'.json',
                           version_id='offline-approved-version', sha256='a'*64)
        self.control = dict(version=1, account=self.config['account'], region=self.config['region'],
                            deployment_id=self.config['deployment_id'], record_bucket=self.source['bucket'],
                            record_key=self.source['key'], record_version_id=self.source['version_id'],
                            record_sha256=self.source['sha256'], configuration_sha256=self.deployment['configuration_sha256'],
                            enabled=True, updated_at=self.deployment['repository_access_granted_at'])

    def load(self, control=None, error=None, raw=None):
        def aws(config, *args):
            self.assertEqual(args[:2], ('s3api', 'get-object'))
            self.assertNotIn('--version-id', args)
            self.assertEqual(args[args.index('--key')+1], 'cleanup/status/'+config['deployment_id']+'.json')
            self.assertEqual(args[args.index('--expected-bucket-owner')+1], config['account'])
            if error: raise error
            Path(args[-1]).write_text(raw if raw is not None else json.dumps(self.control if control is None else control))
            return {}
        with patch.object(ec2, 'aws', side_effect=aws), patch.object(status, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = self.now
            return status.load_status(self.config, self.source, self.deployment)

    def test_latest_status_read_and_unchanged_status_remains_valid(self):
        self.assertEqual(self.load(), self.control)

    def test_canceled_and_nonboolean_status_rejected(self):
        for value in [False, 1, 'true', None]:
            with self.subTest(value=value), self.assertRaises(ec2.CleanupError): self.load(self.control | {'enabled': value})

    def test_stale_authorization_and_tampering_rejected(self):
        for key in ['record_version_id', 'record_sha256', 'record_key', 'record_bucket', 'configuration_sha256']:
            with self.subTest(key=key), self.assertRaises(ec2.CleanupError): self.load(self.control | {key: 'old-or-tampered'})

    def test_wrong_deployment_account_region_rejected(self):
        for key in ['deployment_id', 'account', 'region']:
            with self.subTest(key=key), self.assertRaises(ec2.CleanupError): self.load(self.control | {key: 'other'})

    def test_missing_and_denied_status_fail_closed(self):
        for error in [OSError('private missing path'), ec2.CleanupError('AWS read failed')]:
            with self.subTest(error=type(error)), self.assertRaises(ec2.CleanupError) as caught: self.load(error=error)
            self.assertNotIn('private', str(caught.exception))

    def test_malformed_fields_duplicate_keys_and_timestamp_rejected(self):
        missing = self.control.copy(); del missing['enabled']
        for control in [missing, self.control | {'extra': True}, self.control | {'version': True},
                        self.control | {'updated_at': '2031-01-01T00:00:00Z'},
                        self.control | {'updated_at': '2029-01-01T00:00:00Z'}, self.control | {'updated_at': 'bad'}]:
            with self.subTest(control=control), self.assertRaises(ec2.CleanupError): self.load(control)
        for raw in ['not JSON', '{"enabled":true,"enabled":false}']:
            with self.subTest(raw=raw), self.assertRaises(ec2.CleanupError): self.load(raw=raw)

    def test_current_authorization_rechecks_record_time_after_status_read(self):
        events = []
        with patch.object(ec2, 'authorize', side_effect=lambda *a: events.append('approval')), \
             patch.object(record, 'load_record', side_effect=lambda *a: self.deployment), \
             patch.object(status, 'load_status', side_effect=lambda *a: events.append('latest-status')), \
             patch.object(record, 'validate_record', side_effect=lambda *a: events.append('time')):
            ec2.check_current_authorization(self.config, self.inputs, 'offline-approval', self.source, 'offline-config')
        self.assertEqual(events, ['approval', 'latest-status', 'time', 'approval'])

    def canceled_cleanup(self, checks):
        snapshot = test_ec2.snapshot(self.config)
        def aws(config, *args):
            if args[0] == 'sts': return {'Account': config['account']}
            if args[1] == 'get-bucket-location': return {'LocationConstraint': config['region']}
            if args[0] == 'dynamodb':
                return {'Table': dict(TableStatus='ACTIVE', TableArn=f"arn:aws:dynamodb:{config['region']}:{config['account']}:table/{config['lock_table']}",
                                      KeySchema=[dict(AttributeName='LockID', KeyType='HASH')], AttributeDefinitions=[dict(AttributeName='LockID', AttributeType='S')])}
            if args[1] == 'list-objects-v2': return {'Contents': [{'Key': config['key']}]}
            if args[1] == 'get-object': Path(args[-1]).write_text(json.dumps(snapshot)); return {}
            raise AssertionError('Unexpected AWS call')
        plan = {'resource_changes': [dict(address='aws_vpc.this', mode='managed', type='aws_vpc', name='this',
                                         change=dict(actions=['delete'], before=snapshot['resources'][0]['instances'][0]['attributes']))]}
        commands = []
        def command(args):
            commands.append(args)
            if 'version' in args: return '{"terraform_version":"1.15.8"}'
            if 'show' in args: return json.dumps(plan)
            if 'init' in args or 'plan' in args: return ''
            raise AssertionError('Apply or unexpected command must not be reached')
        with patch.dict(ec2.os.environ, {'CODEBUILD_BUILD_ID': self.config['deployment_id']+'-destroy:offline', 'CODEBUILD_RESOLVED_SOURCE_VERSION': self.config['source_sha']}), \
             patch.object(ec2, 'authorize'), patch.object(ec2, 'source_files', return_value={}), \
             patch.object(ec2, 'aws', side_effect=aws), patch.object(ec2, 'command', side_effect=command), \
             patch.object(ec2, 'check_current_authorization', side_effect=checks):
            with self.assertRaisesRegex(ec2.CleanupError, 'canceled'):
                ec2.cleanup(self.config, self.inputs, True, 'offline-approval', self.source, 'offline-config')
        return commands

    def test_cancellation_before_planning_prevents_all_terraform_commands(self):
        self.assertEqual(self.canceled_cleanup([ec2.CleanupError('Teardown canceled')]), [])

    def test_cancellation_after_planning_prevents_apply(self):
        commands = self.canceled_cleanup([None, ec2.CleanupError('Teardown canceled')])
        self.assertTrue(any('plan' in args for args in commands))
        self.assertFalse(any('apply' in args for args in commands))

    def test_nonboolean_execution_flag_rejected_before_any_calls(self):
        for value in ['false', 'true', 1, None]:
            with self.subTest(value=value), patch.object(ec2, 'command') as command, patch.object(ec2, 'aws') as aws:
                with self.assertRaisesRegex(ec2.CleanupError, 'explicit boolean'): ec2.cleanup(self.config, self.inputs, value)
                command.assert_not_called(); aws.assert_not_called()


if __name__ == '__main__':
    unittest.main()
