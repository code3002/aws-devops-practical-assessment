"""Run on the EC2 host through SSM; configuration contains identifiers, never passwords."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REGION = 'ap-south-1'
RUNTIME = Path('/opt/assessment/runtime')


def aws(*args):
    result = subprocess.run(['aws', '--no-cli-pager', '--region', REGION, '--output', 'json', *args],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError('AWS read failed')
    return json.loads(result.stdout)


def validate(config):
    if set(config) != {'account', 'region', 'host', 'admin_secret_arn', 'app_secret_arn', 'ca_sha256', 'image_id'}:
        raise ValueError('Unexpected configuration')
    if config['region'] != REGION or not re.fullmatch(r'\d{12}', config['account']):
        raise ValueError('Invalid identity')
    if not re.fullmatch(r'[a-z0-9.-]+\.ap-south-1\.rds\.amazonaws\.com', config['host']):
        raise ValueError('Use the exact Mumbai RDS endpoint')
    for key in ['admin_secret_arn', 'app_secret_arn']:
        if not re.fullmatch(r'arn:aws:secretsmanager:ap-south-1:' + config['account'] + r':secret:[A-Za-z0-9/_+=.@!-]+', config[key]):
            raise ValueError('Secret identity mismatch')
    if config['admin_secret_arn'] == config['app_secret_arn']:
        raise ValueError('Separate secrets required')
    if not re.fullmatch(r'[a-f0-9]{64}', config['ca_sha256']) or not re.fullmatch(r'sha256:[a-f0-9]{64}', config['image_id']):
        raise ValueError('Reviewed CA checksum and local image ID required')


def secret(arn, username):
    response = aws('secretsmanager', 'get-secret-value', '--secret-id', arn, '--version-stage', 'AWSCURRENT')
    value = json.loads(response['SecretString'])
    if response['ARN'] != arn or value.get('username') != username:
        raise ValueError('Unexpected secret identity')
    password = value.get('password')
    if not isinstance(password, str) or not password:
        raise ValueError('Missing secret')
    return password


def runtime_text(host, password):
    # A generated base64url password avoids Compose interpolation and quoting ambiguity.
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,128}', password):
        raise ValueError('Application secret requires a generated base64url password')
    return (f'PGHOST={host}\nPGPORT=5432\nPGDATABASE=assessment\nPGUSER=assessment_app\n'
            f'PGPASSWORD={password}\nPGSSLMODE=verify-full\nPGSSLROOTCERT=/certs/rds-ca.pem\n')


def configure(config):
    validate(config)
    if os.geteuid() != 0:
        raise ValueError('Run as root through SSM')
    if aws('sts', 'get-caller-identity')['Account'] != config['account']:
        raise ValueError('AWS account mismatch')
    for path in [Path('/opt/assessment'), RUNTIME, RUNTIME / 'certs']:
        if path.is_symlink() or not path.is_dir() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
            raise ValueError('Root-controlled directories must exist')
    ca = RUNTIME / 'certs/rds-ca.pem'
    if ca.is_symlink() or not ca.is_file() or ca.stat().st_uid != 0 or ca.stat().st_mode & 0o022:
        raise ValueError('CA file must be root-controlled')
    if (RUNTIME / 'certs').stat().st_mode & 0o005 != 0o005 or ca.stat().st_mode & 0o004 == 0:
        raise ValueError('Public CA must be readable by the non-root application container')
    if ca.is_symlink() or hashlib.sha256(ca.read_bytes()).hexdigest() != config['ca_sha256']:
        raise ValueError('CA integrity mismatch')
    with (RUNTIME.parent / 'deploy.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another deployment or database setup is running') from None
        admin = secret(config['admin_secret_arn'], 'assessment_admin')
        app = secret(config['app_secret_arn'], 'assessment_app')
        content = runtime_text(config['host'], app)
        payload = json.dumps({'host': config['host'], 'adminPassword': admin, 'appPassword': app})
        result = subprocess.run(['docker', 'run', '--rm', '-i', '--network', 'host', '--user', '0', '--read-only', '--cap-drop', 'ALL',
                                 '--security-opt', 'no-new-privileges',
                                 '--entrypoint', 'node', '-v', str(Path(__file__).resolve().parent) + ':/integration:ro',
                                 '-v', str(RUNTIME / 'certs') + ':/certs:ro', config['image_id'],
                                 '/integration/initialize.cjs'], input=payload, text=True, capture_output=True)
        if result.returncode:
            raise ValueError('Database initialization or application-access check failed')
        fd, temporary = tempfile.mkstemp(prefix='.app.env.', dir=RUNTIME)
        try:
            with os.fdopen(fd, 'w') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, RUNTIME / 'app.env')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        print('Database initialized; application access verified; private runtime file ready')


if __name__ == '__main__':
    try:
        configure(json.loads(Path(sys.argv[1]).read_text()))
    except Exception:
        raise SystemExit('Database configuration failed; details withheld')
