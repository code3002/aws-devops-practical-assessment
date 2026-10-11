import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import prepare
import artifact


def config():
    return dict(account='123456789012', region='ap-south-1', host='db.example.ap-south-1.rds.amazonaws.com',
                admin_secret_arn='arn:aws:secretsmanager:ap-south-1:123456789012:secret:admin-test',
                app_secret_arn='arn:aws:secretsmanager:ap-south-1:123456789012:secret:app-test',
                ca_sha256='a'*64, bucket='test-artifacts', version_id='exact-version', revision='b'*40,
                artifact_sha256='c'*64, initialize=True)


class PreparationTests(unittest.TestCase):
    def test_invalid_input_stops_before_host_or_aws(self):
        for changes in [{'initialize': 'true'}, {'password': 'never-allowed'}, {'version_id': 'null'},
                        {'version_id': '--bad'}, {'version_id': 'with space'}, {'revision': 'main'}, {'region': 'us-east-1'}]:
            with patch.object(prepare, 'run') as host, patch.object(prepare.configure, 'aws') as aws:
                with self.assertRaises(ValueError): prepare.prepare(config() | changes)
                host.assert_not_called(); aws.assert_not_called()

    def test_nonroot_stops_before_aws(self):
        with patch.object(prepare.os, 'geteuid', return_value=1000), patch.object(prepare.configure, 'aws') as aws:
            with self.assertRaises(ValueError): prepare.prepare(config())
            aws.assert_not_called()

    def test_command_failure_withholds_output(self):
        with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, 'secret-value', 'secret-value')):
            with self.assertRaises(ValueError) as error: prepare.run(['docker', 'build'])
        self.assertNotIn('secret-value', str(error.exception))

    def flow(self, initialize, corrupt=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); runtime = root/'runtime'; runtime.mkdir(mode=0o750)
            certs = runtime/'certs'; certs.mkdir(mode=0o755)
            (certs/'rds-ca.pem').write_bytes(b'fixture CA'); (certs/'rds-ca.pem').chmod(0o644)
            c = config(); c['initialize'] = initialize
            c['ca_sha256'] = hashlib.sha256(b'fixture CA').hexdigest()
            c['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
            c['artifact_sha256'] = artifact.package(c['revision'], root/'source.tar.gz')
            env = runtime/'app.env'
            env.write_text('PGHOST='+c['host']+'\nPGUSER=assessment_app\nPGDATABASE=assessment\nPGSSLMODE=verify-full\nPGSSLROOTCERT=/certs/rds-ca.pem\n'); env.chmod(0o600)
            events = []
            def aws(*args):
                if args[0] == 'sts': return {'Account': c['account']}
                self.assertIn('--expected-bucket-owner', args)
                if corrupt: Path(args[-1]).write_bytes(b'corrupt')
                else: shutil.copyfile(root/'source.tar.gz', args[-1])
                return {'VersionId': c['version_id']}
            def command(args):
                events.append(args[0:2])
                if args[0] == 'uname': return 'Linux x86_64'
                if args[:3] == ['docker', 'image', 'inspect']: return 'sha256:'+'d'*64
                return ''
            def configure(values):
                events.append(['initialize'])
                self.assertEqual(values['image_id'], 'sha256:'+'d'*64)
                # configure must acquire the lock independently: no nested deployment lock.
                import fcntl
                with (root/'deploy.lock').open('a') as lock: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            original = Path.stat
            def stat(path, *args, **kwargs):
                values = list(original(path, *args, **kwargs)); values[4] = 0
                return os.stat_result(values)
            with patch.object(prepare, 'ROOT', root), patch.object(Path, 'stat', stat), patch.object(prepare.os, 'geteuid', return_value=0), patch.object(prepare, 'run', side_effect=command), patch.object(prepare.configure, 'aws', side_effect=aws), patch.object(prepare.configure, 'configure', side_effect=configure), patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', '')), contextlib.redirect_stdout(io.StringIO()):
                if corrupt:
                    with self.assertRaisesRegex(ValueError, 'integrity'): prepare.prepare(c)
                    self.assertNotIn(['docker', 'build'], events)
                    self.assertNotIn(['initialize'], events)
                else:
                    prepare.prepare(c)
                    if initialize:
                        self.assertLess(events.index(['docker', 'build']), events.index(['initialize']))
                        self.assertLess(events.index(['initialize']), next(i for i, e in enumerate(events) if e[0] == 'bash'))
                    else:
                        self.assertNotIn(['initialize'], events)
                        self.assertNotIn(['docker', 'build'], events)

    def test_initial_setup_builds_before_database_then_deploys(self): self.flow(True)
    def test_subsequent_deployment_preserves_existing_credentials(self): self.flow(False)
    def test_corrupt_artifact_never_builds_or_initializes(self): self.flow(True, corrupt=True)


if __name__ == '__main__': unittest.main()
