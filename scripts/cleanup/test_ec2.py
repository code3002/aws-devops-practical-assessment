import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import ec2


def fixture():
    # Synthetic offline identifiers only; never contact AWS or Terraform.
    return dict(account='123456789012', region='ap-south-1', deployment_id='test-assessment',
                bucket='test-state-bucket', key='ec2/terraform.tfstate', lock_table='test-locks',
                state_lineage='test-lineage', never_deployed=False, inputs_file='not-used',
                inputs_sha256='a'*64, source_sha='b'*40)


def snapshot(config):
    tags = dict(DeploymentId=config['deployment_id'], Component='ec2', Project='aws-devops-practical-assessment')
    return dict(version=4, lineage=config['state_lineage'], resources=[dict(mode='managed',
        type='aws_vpc', name='this', instances=[dict(attributes=dict(id='vpc-test', tags_all=tags))])])


class CleanupTests(unittest.TestCase):
    def dry_run(self, config, state=None, missing=False, fail=False):
        def fake_aws(c, *args):
            if fail: raise ec2.CleanupError('AWS read failed')
            if args[0] == 'sts': return {'Account': c['account']}
            if args[1] == 'get-bucket-location': return {'LocationConstraint': c['region']}
            if args[0] == 'dynamodb':
                return {'Table': dict(TableStatus='ACTIVE', TableArn=f"arn:aws:dynamodb:{c['region']}:{c['account']}:table/{c['lock_table']}", KeySchema=[dict(AttributeName='LockID', KeyType='HASH')], AttributeDefinitions=[dict(AttributeName='LockID', AttributeType='S')])}
            if args[1] == 'list-objects-v2': return {'Contents': [] if missing else [dict(Key=c['key'])]}
            if args[1] == 'get-object': Path(args[-1]).write_text(json.dumps(state)); return {}
            raise AssertionError('Unexpected AWS command')
        output = io.StringIO()
        with patch.object(ec2, 'aws', side_effect=fake_aws), patch.object(ec2, 'source_files', return_value={}), patch.object(ec2, 'command') as command, contextlib.redirect_stdout(output):
            ec2.cleanup(config, b'{}')
            command.assert_not_called()
        return output.getvalue()

    def test_dry_run_success_without_terraform(self):
        c = fixture(); self.assertIn('DRY RUN', self.dry_run(c, snapshot(c)))

    def test_absent_state_only_allowed_when_explicitly_undeployed(self):
        c = fixture()
        with self.assertRaisesRegex(ec2.CleanupError, 'state missing'): self.dry_run(c, missing=True)
        c.update(never_deployed=True, state_lineage=None)
        self.assertIn('undeployed', self.dry_run(c, missing=True))

    def test_repeated_completed_jobs_do_nothing(self):
        c = fixture(); state = snapshot(c); state['resources'] = []
        for _ in range(2): self.assertIn('already empty', self.dry_run(c, state))

    def test_failure_then_manual_retry(self):
        c = fixture()
        with self.assertRaisesRegex(ec2.CleanupError, 'AWS read failed'): self.dry_run(c, fail=True)
        self.assertIn('DRY RUN', self.dry_run(c, snapshot(c)))

    def test_wrong_account_stops_before_backend_reads(self):
        c = fixture()
        with patch.object(ec2, 'source_files', return_value={}), patch.object(ec2, 'aws', return_value={'Account': '999999999999'}) as aws:
            with self.assertRaisesRegex(ec2.CleanupError, 'account mismatch'): ec2.cleanup(c, b'{}')
            self.assertEqual(aws.call_count, 1)

    def test_state_lineage_tags_and_unexpected_resources(self):
        c = fixture()
        for mutation in ['lineage', 'tags', 'type', 'module', 'deposed']:
            state = snapshot(c)
            if mutation == 'lineage': state['lineage'] = 'other-history'
            elif mutation == 'tags': state['resources'][0]['instances'][0]['attributes']['tags_all']['DeploymentId'] = 'other-deployment'
            elif mutation == 'type': state['resources'][0]['type'] = 'aws_s3_bucket'
            elif mutation == 'module': state['resources'][0]['module'] = 'module.other'
            else: state['resources'][0]['instances'][0]['deposed'] = 'old'
            with self.subTest(mutation=mutation), self.assertRaises(ec2.CleanupError): ec2.state_resources(c, state)

    def test_untagged_resource_requires_owned_parent(self):
        c = fixture(); state = snapshot(c)
        state['resources'].append(dict(mode='managed', type='aws_route', name='internet', instances=[dict(attributes=dict(id='route-test', route_table_id='foreign-table'))]))
        with self.assertRaisesRegex(ec2.CleanupError, 'parent mismatch'): ec2.state_resources(c, state)

    def test_delete_only_plan_and_refreshed_ownership(self):
        c = fixture(); resource = dict(address='aws_vpc.this', type='aws_vpc', name='this', mode='managed', change=dict(actions=['delete'], before=snapshot(c)['resources'][0]['instances'][0]['attributes']))
        plan = dict(resource_changes=[resource]); ec2.validate_plan(plan, {'aws_vpc.this'}, c, snapshot(c))
        for action in [['create'], ['update'], ['delete','create']]:
            resource['change']['actions'] = action
            with self.assertRaises(ec2.CleanupError): ec2.validate_plan(plan, {'aws_vpc.this'}, c, snapshot(c))
        resource['change']['actions'] = ['delete']; resource['change']['before']['tags_all']['DeploymentId'] = 'other'
        with self.assertRaises(ec2.CleanupError): ec2.validate_plan(plan, {'aws_vpc.this'}, c, snapshot(c))

    def test_authorization_scope_and_expiry_without_execution(self):
        c = fixture()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'approval.json'
            approval = dict(action='DESTROY_EC2_STACK', configuration_sha256=hashlib.sha256(json.dumps(c, sort_keys=True).encode()).hexdigest(), expires_at=(datetime.now(timezone.utc)+timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ'))
            path.write_text(json.dumps(approval)); ec2.authorize(c, path)
            for change in [dict(action='OTHER'), dict(configuration_sha256='c'*64), dict(expires_at='2000-01-01T00:00:00Z')]:
                path.write_text(json.dumps(approval | change))
                with self.assertRaises(ec2.CleanupError): ec2.authorize(c, path)
        with self.assertRaises(ec2.CleanupError): ec2.authorize(c, None)

    def test_source_revision_mismatch_rejects_before_aws(self):
        c = fixture()
        with patch.object(ec2, 'command', return_value='c'*40), patch.object(ec2, 'aws') as aws:
            with self.assertRaisesRegex(ec2.CleanupError, 'Source revision mismatch'): ec2.cleanup(c, b'{}')
            aws.assert_not_called()

    def test_retained_configuration_and_inputs(self):
        c = fixture()
        values = dict(aws_region=c['region'], expected_account_id=c['account'], deployment_id=c['deployment_id'], vpc_cidr='10.10.0.0/16', reviewer_ssh_cidr='192.0.2.1/32', reviewed_ami_id='ami-'+'a'*17, postgres_version='17.11', ssh_key_name=None)
        with tempfile.TemporaryDirectory() as d:
            inputs = Path(d)/'inputs.json'; inputs.write_text(json.dumps(values))
            c.update(inputs_file=str(inputs), inputs_sha256=hashlib.sha256(inputs.read_bytes()).hexdigest())
            config = Path(d)/'config.json'; config.write_text(json.dumps(c)); ec2.configuration(config)
            for key, value in [('region','other'), ('key','bootstrap/terraform.tfstate'), ('deployment_id','other-deployment'), ('inputs_sha256','f'*64)]:
                config.write_text(json.dumps(c | {key:value}))
                with self.assertRaises(ec2.CleanupError): ec2.configuration(config)

    def test_command_failure_does_not_expose_output(self):
        with patch.object(ec2.subprocess, 'run', return_value=subprocess.CompletedProcess([],1,'sensitive-output','sensitive-output')):
            with self.assertRaises(ec2.CleanupError) as error: ec2.command(['aws','sts'])
        self.assertNotIn('sensitive-output', str(error.exception))

    def test_terraform_source_requires_exact_committed_files(self):
        c = fixture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stack = root/'infrastructure/terraform/ec2'
            stack.mkdir(parents=True)
            helper = root/'scripts/host/bootstrap.sh'
            helper.parent.mkdir(parents=True)
            helper.write_text('#!/bin/bash\necho bootstrap\n')
            for name in ec2.HELPERS[1:]:
                path = root/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# helper\n')
            files = {'main.tf': 'resource "aws_vpc" "this" {}\n', '.terraform.lock.hcl': '# lock\n'}
            for name, content in files.items(): (stack/name).write_text(content)
            def git(args):
                if 'rev-parse' in args: return c['source_sha']
                if 'ls-tree' in args: return '\n'.join('infrastructure/terraform/ec2/' + name for name in files)
                for name in ec2.HELPERS:
                    if args[-1].endswith(name): return (root/name).read_text()
                return files[args[-1].split('/')[-1]]
            with patch.object(ec2, 'STACK', stack), patch.object(ec2, 'ROOT', root), patch.object(ec2, 'command', side_effect=git):
                self.assertEqual(ec2.source_files(c), {name: content.encode() for name, content in files.items()} | {'../../../' + name: (root/name).read_bytes() for name in ec2.HELPERS})
                with patch.object(ec2, 'command', side_effect=lambda args: '# changed bootstrap\n' if args[-1].endswith('scripts/host/bootstrap.sh') else git(args)):
                    with self.assertRaisesRegex(ec2.CleanupError, 'Bootstrap source differs'): ec2.source_files(c)
                (stack/'main.tf').write_text('unreviewed configuration')
                with self.assertRaisesRegex(ec2.CleanupError, 'differs'): ec2.source_files(c)
                (stack/'main.tf').write_text(files['main.tf'])
                (stack/'extra.tf').write_text('unreviewed provisioner')
                with self.assertRaisesRegex(ec2.CleanupError, 'inventory'): ec2.source_files(c)

    def test_isolated_source_keeps_bootstrap_relative_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            stack = ec2.stage_source(root, {'main.tf': b'# terraform', '../../../scripts/host/bootstrap.sh': b'#!/bin/bash'})
            self.assertEqual((stack/'../../../scripts/host/bootstrap.sh').read_bytes(), b'#!/bin/bash')
            self.assertTrue((stack/'../../../scripts/host/bootstrap.sh').resolve().is_relative_to(root.resolve()))
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ec2.CleanupError, 'staged source path'):
                ec2.stage_source(Path(d), {'../../../../escape': b'bad'})

    def test_inline_policy_requires_exact_owned_role_and_count_index(self):
        c = fixture(); state = snapshot(c)
        state['resources'] += [
            dict(mode='managed', type='aws_iam_role', name='app', instances=[dict(attributes=dict(id=c['deployment_id']+'-ec2-ssm', tags_all=state['resources'][0]['instances'][0]['attributes']['tags_all']))]),
            dict(mode='managed', type='aws_iam_role_policy', name='runtime', instances=[dict(index_key=0, attributes=dict(id='policy-test', role=c['deployment_id']+'-ec2-ssm'))])]
        self.assertIn('aws_iam_role_policy.runtime[0]', ec2.state_resources(c, state))
        state['resources'][-1]['instances'][0]['attributes']['role'] = 'foreign-role'
        with self.assertRaisesRegex(ec2.CleanupError, 'Inline policy parent'): ec2.state_resources(c, state)

    def test_new_resources_and_bucket_settings_are_owned(self):
        c = fixture(); state = snapshot(c)
        tags = state['resources'][0]['instances'][0]['attributes']['tags_all']
        def add(kind, name, identifier, index=None, **attributes):
            instance = dict(attributes=dict(id=identifier, tags_all=tags, **attributes))
            if index is not None: instance['index_key'] = index
            state['resources'].append(dict(mode='managed', type=kind, name=name, instances=[instance]))
        add('aws_subnet', 'this', 'subnet-test', 'public_a')
        add('aws_route_table', 'private', 'rtb-test')
        add('aws_eip', 'nat', 'eipalloc-test')
        add('aws_nat_gateway', 'this', 'nat-test', allocation_id='eipalloc-test', subnet_id='subnet-test')
        add('aws_route', 'private_nat', 'route-test', route_table_id='rtb-test', nat_gateway_id='nat-test')
        add('aws_s3_bucket', 'artifacts', 'owned-artifacts', 0)
        for kind in ['aws_s3_bucket_public_access_block', 'aws_s3_bucket_ownership_controls',
                     'aws_s3_bucket_server_side_encryption_configuration', 'aws_s3_bucket_versioning', 'aws_s3_bucket_policy']:
            add(kind, 'artifacts', 'owned-artifacts', 0, bucket='owned-artifacts')
        add('aws_secretsmanager_secret', 'application', 'secret-test', 0)
        add('aws_ssm_document', 'deploy', 'document-test')
        self.assertIn('aws_s3_bucket.artifacts[0]', ec2.state_resources(c, state))
        state['resources'][-3]['instances'][0]['attributes']['bucket'] = 'shared-state-bucket'
        with self.assertRaisesRegex(ec2.CleanupError, 'bucket parent'): ec2.state_resources(c, state)

    def test_manual_mode_requires_execute_and_explicit_authorization(self):
        with patch.object(ec2, 'aws') as aws:
            with self.assertRaises(ec2.CleanupError): ec2.cleanup(fixture(), b'{}', manual=True)
            with self.assertRaises(ec2.CleanupError): ec2.cleanup(fixture(), b'{}', execute=True, manual=True)
            aws.assert_not_called()

    def test_manual_mode_still_checks_current_record_and_cancellation(self):
        with patch.object(ec2, 'authorize') as authorize, patch.object(ec2, 'check_current_authorization', side_effect=ec2.CleanupError('Canceled')) as current, patch.object(ec2, 'source_files') as source:
            with self.assertRaisesRegex(ec2.CleanupError, 'Canceled'):
                ec2.cleanup(fixture(), b'{}', execute=True, manual=True, approval='reviewed', record_source={'approved': True}, configuration_path='retained.json')
            authorize.assert_called_once(); current.assert_called_once(); source.assert_not_called()

    def test_optional_terraform_defaults_are_valid_retained_inputs(self):
        c = fixture()
        values = dict(expected_account_id=c['account'], deployment_id=c['deployment_id'],
                      reviewer_ssh_cidr='192.0.2.1/32', reviewed_ami_id='ami-'+'a'*17, postgres_version='17.11')
        with tempfile.TemporaryDirectory() as d:
            inputs = Path(d)/'inputs.json'; inputs.write_text(json.dumps(values))
            c.update(inputs_file=str(inputs), inputs_sha256=hashlib.sha256(inputs.read_bytes()).hexdigest())
            path = Path(d)/'config.json'; path.write_text(json.dumps(c))
            self.assertEqual(ec2.configuration(path)[1], inputs.read_bytes())
            for extra, valid in [
                ({'artifact_bucket': 'test-artifacts', 'app_secret_arn': 'arn:aws:secretsmanager:ap-south-1:123456789012:secret:app-test'}, True),
                ({'artifact_bucket': c['bucket']}, False),
                ({'app_secret_arn': 'arn:aws:secretsmanager:ap-south-1:999999999999:secret:app-test'}, False),
            ]:
                inputs.write_text(json.dumps(values | extra))
                c['inputs_sha256'] = hashlib.sha256(inputs.read_bytes()).hexdigest()
                path.write_text(json.dumps(c))
                if valid: ec2.configuration(path)
                else:
                    with self.assertRaises(ec2.CleanupError): ec2.configuration(path)

    def test_abbreviated_execute_flag_is_rejected_before_configuration(self):
        result = subprocess.run(['python3', '-B', str(Path(ec2.__file__)), 'not-used', '--exec'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('unrecognized arguments', result.stderr)

    def test_environment_cannot_select_execution(self):
        with patch.dict(ec2.os.environ, {'EXECUTE': 'true', 'TF_CLI_ARGS': '-destroy'}):
            c = fixture()
            self.assertIn('DRY RUN', self.dry_run(c, snapshot(c)))


if __name__ == '__main__': unittest.main()
