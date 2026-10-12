import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

import codebuild
import ec2
import record
import status
import test_ec2
import test_record


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.config = test_ec2.fixture() | {'inputs_file': 'inputs.tfvars.json'}
        self.env = dict(EXPECTED_ACCOUNT_ID=self.config['account'], AWS_REGION=self.config['region'],
                        DEPLOYMENT_ID=self.config['deployment_id'], EXPECTED_SOURCE_COMMIT=self.config['source_sha'],
                        CODEBUILD_RESOLVED_SOURCE_VERSION=self.config['source_sha'], BACKEND_BUCKET=self.config['bucket'])
        self.delivery = {key: {} for key in ['configuration', 'inputs', 'record']}
        self.env['CLEANUP_DELIVERY'] = json.dumps(self.delivery)

    def run_build(self, changes=None, status_error=None, record_error=None, version='1.15.8', config=None, cleanup_error=None):
        def command(args):
            if args[0] == 'git': return self.config['source_sha']
            if args[:2] == ['terraform', 'version']: return json.dumps({'terraform_version': version})
            raise AssertionError('Unexpected subprocess')
        def download(source, identity, key, path):
            path.write_text(json.dumps(self.config if path.name == 'config.json' else {}))
        previous = Path.cwd()
        with patch.dict(os.environ, self.env | (changes or {}), clear=True), \
             patch.object(ec2, 'command', side_effect=command), \
             patch.object(ec2, 'aws', return_value={'Account': self.config['account']}), \
             patch.object(codebuild, 'download', side_effect=download), \
             patch.object(ec2, 'configuration', return_value=(config or self.config, b'{}')), \
             patch.object(record, 'load_record', side_effect=record_error, return_value={}) as loader, \
             patch.object(status, 'load_status', side_effect=status_error), patch.object(ec2, 'cleanup', side_effect=cleanup_error) as cleanup:
            try:
                codebuild.run()
                self.assertFalse(cleanup.call_args.kwargs['execute'])
                self.assertIsNone(cleanup.call_args.kwargs['approval'])
                self.assertTrue(loader.call_args.kwargs['preflight'])
            finally:
                self.assertEqual(Path.cwd(), previous)

    def test_buildspec_invokes_runner_and_defaults_to_preflight(self):
        text = (Path(codebuild.__file__).parent/'buildspec.yml').read_text()
        self.assertIn('python3 -B scripts/cleanup/codebuild.py', text)
        self.assertNotIn('terraform ', text)
        self.run_build()

    def test_wrong_source_and_tool_version_fail(self):
        with self.assertRaises(ec2.CleanupError): self.run_build({'CODEBUILD_RESOLVED_SOURCE_VERSION': 'c'*40})
        with self.assertRaises(ec2.CleanupError): self.run_build(version='other')

    def test_unknown_mode_and_missing_authorization_fail(self):
        for mode in ['true', 'DESTROY_EC2_STACK']:
            with self.subTest(mode=mode), self.assertRaises(ec2.CleanupError): self.run_build({'EXECUTION_MODE': mode})

    def test_cancellation_missing_state_and_record_failure_propagate(self):
        with self.assertRaises(ec2.CleanupError): self.run_build(status_error=ec2.CleanupError('Canceled'))
        with self.assertRaises(ec2.CleanupError): self.run_build(record_error=ec2.CleanupError('Missing record'))
        with self.assertRaisesRegex(ec2.CleanupError, 'state missing'):
            self.run_build(cleanup_error=ec2.CleanupError('Deployed state missing'))

    def test_retained_configuration_mismatch_fails(self):
        with self.assertRaises(ec2.CleanupError): self.run_build(config=self.config | {'deployment_id': 'other'})

    def test_versioned_download_integrity_and_owner(self):
        data = b'{}'
        source = dict(bucket=self.config['bucket'], key='approved', version_id='offline-version', sha256=record.digest(data))
        def aws(config, *args):
            self.assertEqual(args[:2], ('s3api', 'get-object'))
            self.assertEqual(args[args.index('--version-id')+1], source['version_id'])
            self.assertEqual(args[args.index('--expected-bucket-owner')+1], config['account'])
            Path(args[-1]).write_bytes(data)
            return {'VersionId': source['version_id']}
        with tempfile.TemporaryDirectory() as directory, patch.object(ec2, 'aws', side_effect=aws):
            codebuild.download(source, self.config, 'approved', Path(directory)/'data')
            with self.assertRaises(ec2.CleanupError):
                codebuild.download(source | {'sha256': 'f'*64}, self.config, 'approved', Path(directory)/'bad')

    def test_preflight_can_inspect_future_deadline_but_execution_cannot(self):
        fixture = test_record.RecordTests(); fixture.setUp()
        with patch.object(record, 'datetime', wraps=test_record.datetime) as clock:
            clock.now.return_value = fixture.now-test_record.timedelta(hours=1)
            record.validate_record(fixture.data, fixture.config, fixture.inputs, preflight=True)
            with self.assertRaises(ec2.CleanupError): record.validate_record(fixture.data, fixture.config, fixture.inputs)
            with self.assertRaises(ec2.CleanupError): record.validate_record(fixture.data, fixture.config, fixture.inputs, preflight='true')

    def test_installer_rejects_non_codebuild_environment(self):
        installer = Path(codebuild.__file__).parent/'install_terraform.sh'
        environment = os.environ.copy(); environment.pop('CODEBUILD_BUILD_ID', None)
        result = subprocess.run(['bash', str(installer)], env=environment, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires Linux x86_64 CodeBuild', result.stderr)

    def test_installer_checksum_failure_stops_before_extraction(self):
        installer = Path(codebuild.__file__).parent/'install_terraform.sh'
        with tempfile.TemporaryDirectory() as directory:
            tools = Path(directory)
            scripts = {
                'uname': '#!/bin/bash\nif [[ "$1" == -s ]]; then echo Linux; else echo x86_64; fi\n',
                'curl': '#!/bin/bash\nwhile [[ $# -gt 0 ]]; do if [[ "$1" == --output ]]; then printf bad-archive > "$2"; exit 0; fi; shift; done\nexit 1\n',
                'unzip': '#!/bin/bash\necho unexpected-extraction >&2\nexit 99\n',
            }
            for name, content in scripts.items():
                path = tools/name; path.write_text(content); path.chmod(0o700)
            environment = os.environ | {'CODEBUILD_BUILD_ID': 'offline-test', 'PATH': str(tools)+':'+os.environ['PATH']}
            result = subprocess.run(['bash', str(installer)], env=environment, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('unexpected-extraction', result.stderr)


if __name__ == '__main__':
    unittest.main()
