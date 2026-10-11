import contextlib
import io
import json
import hashlib
import os
from pathlib import Path
import tempfile
import secrets
import subprocess
import unittest
from unittest.mock import patch
import configure


def config():
    # Synthetic identifiers; tests never invoke AWS or Docker.
    return dict(account='123456789012', region='ap-south-1',
                host='database.example.ap-south-1.rds.amazonaws.com',
                admin_secret_arn='arn:aws:secretsmanager:ap-south-1:123456789012:secret:admin-test',
                app_secret_arn='arn:aws:secretsmanager:ap-south-1:123456789012:secret:app-test',
                ca_sha256='a'*64, image_id='sha256:'+'b'*64)


class ConfigurationTests(unittest.TestCase):
    def test_valid_configuration(self):
        configure.validate(config())

    def test_reject_identity_endpoint_image_and_extra_inputs(self):
        for key, value in [('region', 'us-east-1'), ('account', 'invalid'),
                           ('host', 'localhost'), ('image_id', 'app:latest'),
                           ('ca_sha256', 'invalid'), ('password', secrets.token_urlsafe(32))]:
            with self.subTest(key=key):
                c = config(); c[key] = value
                with self.assertRaises(ValueError): configure.validate(c)

    def test_reject_shared_or_foreign_secret(self):
        for arn in [config()['admin_secret_arn'], 'arn:aws:secretsmanager:ap-south-1:999999999999:secret:app']:
            c = config(); c['app_secret_arn'] = arn
            with self.assertRaises(ValueError): configure.validate(c)

    def test_runtime_tls_and_compose_safe_generated_password(self):
        password = secrets.token_urlsafe(32)
        value = configure.runtime_text(config()['host'], password)
        self.assertIn('PGSSLMODE=verify-full', value)
        self.assertIn('PGSSLROOTCERT=/certs/rds-ca.pem', value)
        self.assertIn('PGUSER=assessment_app', value)
        self.assertIn('PGPASSWORD='+password, value)
        for unsafe in [password+'\n', password+'$', password+"'", '']:
            with self.assertRaises(ValueError): configure.runtime_text(config()['host'], unsafe)

    def test_secret_validation_and_no_output(self):
        arn = config()['app_secret_arn']; password = secrets.token_urlsafe(32)
        response = {'ARN': arn, 'SecretString': json.dumps({'username': 'assessment_app', 'password': password})}
        output = io.StringIO()
        with patch.object(configure, 'aws', return_value=response) as aws, contextlib.redirect_stdout(output):
            self.assertEqual(configure.secret(arn, 'assessment_app'), password)
            self.assertIn('AWSCURRENT', aws.call_args.args)
        self.assertEqual(output.getvalue(), '')
        with patch.object(configure, 'aws', return_value=response):
            with self.assertRaises(ValueError): configure.secret(arn, 'assessment_admin')

    def test_aws_errors_do_not_disclose_response_or_credentials(self):
        password = secrets.token_urlsafe(32)
        failure = subprocess.CompletedProcess([], 1, stdout=password, stderr=password)
        with patch.object(configure.subprocess, 'run', return_value=failure):
            with self.assertRaises(ValueError) as error: configure.aws('sts', 'get-caller-identity')
        self.assertNotIn(password, str(error.exception))

    def test_configuration_writes_only_app_secret_and_preserves_file_on_failure(self):
        for success in [True, False]:
            with self.subTest(success=success), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime = root/'runtime'; runtime.mkdir(mode=0o750)
                certs = runtime/'certs'; certs.mkdir(mode=0o755)
                ca = certs/'rds-ca.pem'; ca.write_bytes(b'local test CA'); ca.chmod(0o644)
                config_values = config(); config_values['ca_sha256'] = hashlib.sha256(ca.read_bytes()).hexdigest()
                admin_password, app_password = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                previous = secrets.token_urlsafe(32)
                (runtime/'app.env').write_text(previous); (runtime/'app.env').chmod(0o600)
                def fake_aws(*args):
                    if args[0] == 'sts': return {'Account': config_values['account']}
                    arn = args[args.index('--secret-id')+1]
                    admin = arn == config_values['admin_secret_arn']
                    return {'ARN': arn, 'SecretString': json.dumps({'username': 'assessment_admin' if admin else 'assessment_app', 'password': admin_password if admin else app_password})}
                original_stat = Path.stat
                def root_stat(path, *args, **kwargs):
                    values = list(original_stat(path, *args, **kwargs)); values[4] = 0
                    return os.stat_result(values)
                captured = io.StringIO()
                with (
                    patch.object(configure, 'RUNTIME', runtime),
                    patch.object(configure, 'Path', side_effect=lambda p: root if str(p) == '/opt/assessment' else Path(p)),
                    patch.object(Path, 'stat', root_stat),
                    patch.object(configure.os, 'geteuid', return_value=0),
                    patch.object(configure, 'aws', side_effect=fake_aws),
                    patch.object(configure.subprocess, 'run', return_value=subprocess.CompletedProcess(
                        [], 0 if success else 1, stdout=admin_password, stderr=app_password)) as docker,
                    contextlib.redirect_stdout(captured),
                ):
                    if success: configure.configure(config_values)
                    else:
                        with self.assertRaises(ValueError): configure.configure(config_values)
                payload = json.loads(docker.call_args.kwargs['input'])
                self.assertEqual(payload['adminPassword'], admin_password)
                self.assertEqual(payload['appPassword'], app_password)
                arguments = ' '.join(docker.call_args.args[0])
                self.assertNotIn(admin_password, arguments); self.assertNotIn(app_password, arguments)
                self.assertNotIn(admin_password, captured.getvalue()); self.assertNotIn(app_password, captured.getvalue())
                result = (runtime/'app.env').read_text()
                self.assertEqual((runtime/'app.env').stat().st_mode & 0o777, 0o600)
                self.assertNotIn(admin_password, result)
                if success: self.assertIn(app_password, result)
                else: self.assertEqual(result, previous)
                self.assertFalse(list(runtime.glob('.app.env.*')))

    def test_secret_transport_and_atomic_private_file_contract(self):
        from pathlib import Path
        source = Path(configure.__file__).read_text()
        self.assertIn('input=payload', source)
        self.assertIn('fcntl.LOCK_EX | fcntl.LOCK_NB', source)
        self.assertIn("RUNTIME.parent / 'deploy.lock'", source)
        self.assertIn('capture_output=True', source)
        self.assertIn('os.fchmod(output.fileno(), 0o600)', source)
        self.assertIn('os.replace(temporary', source)
        self.assertNotIn('put-secret-value', source)
        self.assertNotIn('create-secret', source)


if __name__ == '__main__': unittest.main()
