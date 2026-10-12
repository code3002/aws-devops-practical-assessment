"""AL2023 SSM coordinator. Input contains reviewed identifiers/checksums only."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

# Works in both the repository and the versioned SSM-delivered tools directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'database'))
import configure
import artifact

ROOT = Path('/opt/assessment')


def validate(config):
    required = {'account', 'region', 'host', 'admin_secret_arn', 'app_secret_arn',
                'ca_sha256', 'bucket', 'version_id', 'revision', 'artifact_sha256',
                'image_version_id', 'image_sha256', 'initialize'}
    if set(config) != required or type(config['initialize']) is not bool:
        raise ValueError('Unexpected deployment configuration')
    configure.validate({key: config[key] for key in
                        ['account', 'region', 'host', 'admin_secret_arn', 'app_secret_arn', 'ca_sha256']}
                       | {'image_id': 'sha256:' + '0' * 64})
    if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', config['bucket']):
        raise ValueError('Invalid artifact bucket')
    version = config['version_id']
    if not isinstance(version, str) or not 0 < len(version) <= 1024 or version == 'null' or version.startswith('-') or any(c.isspace() for c in version):
        raise ValueError('Exact artifact version required')
    if not re.fullmatch(r'[a-f0-9]{40}', config['revision']) or not re.fullmatch(r'[a-f0-9]{64}', config['artifact_sha256']):
        raise ValueError('Immutable source and artifact hash required')
    if not isinstance(config['image_version_id'], str) or not config['image_version_id'] or config['image_version_id'] == 'null' or any(c.isspace() for c in config['image_version_id']):
        raise ValueError('Valid image version required')
    if not re.fullmatch(r'[a-f0-9]{64}', config['image_sha256']):
        raise ValueError('Valid image checksum required')


def run(args, env=None):
    result = subprocess.run(args, env=env, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('Host operation failed; output withheld')
    return result.stdout.strip()


def directory(path, mode):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError('Unsafe directory')
    if not path.exists():
        path.mkdir(mode=mode)
    if path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError('Directory must be root-controlled')
    path.chmod(mode)


def prepare(config):
    validate(config)
    if os.geteuid() != 0 or run(['uname', '-sm']) != 'Linux x86_64':
        raise ValueError('Requires the root AL2023 SSM host')
    if configure.aws('sts', 'get-caller-identity')['Account'] != config['account']:
        raise ValueError('Account mismatch')
    if not ROOT.is_dir() or ROOT.is_symlink() or ROOT.stat().st_uid != 0 or ROOT.stat().st_mode & 0o022:
        raise ValueError('Bootstrap directory is unsafe')
    # Serializes this coordinator; individual setup/deploy stages also hold deploy.lock.
    with (ROOT/'prepare.lock').open('a') as coordinator:
        fcntl.flock(coordinator, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime = ROOT/'runtime'
        with tempfile.TemporaryDirectory(prefix='.prepare.', dir=ROOT) as temporary:
            work = Path(temporary)
            with (ROOT/'deploy.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                directory(runtime, 0o750)
                directory(runtime/'certs', 0o755)
                ca = runtime/'certs/rds-ca.pem'
                if ca.is_symlink():
                    raise ValueError('Unsafe CA path')
                if ca.exists():
                    if ca.stat().st_uid != 0 or ca.stat().st_mode & 0o022 or hashlib.sha256(ca.read_bytes()).hexdigest() != config['ca_sha256']:
                        raise ValueError('Existing CA differs; rotation requires review')
                else:
                    with urllib.request.urlopen('https://truststore.pki.rds.amazonaws.com/ap-south-1/ap-south-1-bundle.pem', timeout=30) as response:
                        data = response.read(1024 * 1024 + 1)
                    if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != config['ca_sha256']:
                        raise ValueError('CA checksum mismatch')
                    candidate = work/'ca.pem'; candidate.write_bytes(data); candidate.chmod(0o644)
                    os.replace(candidate, ca)
                if (runtime/'certs').stat().st_mode & 0o005 != 0o005 or ca.stat().st_mode & 0o004 == 0:
                    raise ValueError('CA must be readable by the non-root application')
                image = None
                if config['initialize']:
                    archive = work/'application.tar.gz'
                    metadata = configure.aws('s3api', 'get-object', '--bucket', config['bucket'],
                                             '--key', 'applications/' + config['revision'] + '.tar.gz',
                                             '--version-id', config['version_id'], '--expected-bucket-owner', config['account'], str(archive))
                    if metadata.get('VersionId') != config['version_id'] or hashlib.sha256(archive.read_bytes()).hexdigest() != config['artifact_sha256']:
                        raise ValueError('Artifact integrity mismatch')
                    release = work/'release'; artifact.extract(archive, release)
                    tag = 'assessment-app:' + config['revision'] + '-' + config['artifact_sha256']
                    image_archive = work/'image.tar.gz'
                    image_metadata = configure.aws(
                        's3api', 'get-object', '--region', config['region'],
                        '--bucket', config['bucket'],
                        '--key', 'images/' + config['revision'] + '.tar.gz',
                        '--version-id', config['image_version_id'],
                        '--expected-bucket-owner', config['account'],
                        str(image_archive)
                    )
                    if (image_metadata.get('VersionId') != config['image_version_id']
                            or hashlib.sha256(image_archive.read_bytes()).hexdigest() != config['image_sha256']):
                        raise ValueError('Image artifact integrity mismatch')

                    run(['docker', 'load', '-i', str(image_archive)])
                    run(['docker', 'tag', 'assessment-app:' + config['revision'], tag])
                    image = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', tag])
            # configure.py owns deploy.lock itself; never nest it under the same lock.
            if config['initialize']:
                configure.configure({key: config[key] for key in
                                     ['account', 'region', 'host', 'admin_secret_arn', 'app_secret_arn', 'ca_sha256']}
                                    | {'image_id': image})
            else:
                env = runtime/'app.env'
                if env.is_symlink() or not env.is_file() or env.stat().st_uid != 0 or env.stat().st_mode & 0o777 != 0o600:
                    raise ValueError('Initial database configuration is required')
                values = dict(line.split('=', 1) for line in env.read_text().splitlines())
                if any(values.get(key) != value for key, value in {'PGHOST': config['host'], 'PGUSER': 'assessment_app', 'PGDATABASE': 'assessment', 'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': '/certs/rds-ca.pem'}.items()):
                    raise ValueError('Existing runtime identity differs; reconfiguration requires review')
            env = os.environ.copy()
            env['IMAGE_VERSION_ID'] = config['image_version_id']
            env['IMAGE_SHA256'] = config['image_sha256']
            run(
                ['bash', str(Path(__file__).with_name('deploy.sh')),
                 config['bucket'], config['version_id'],
                 config['revision'], config['artifact_sha256']],
                env=env
            )
    print('SSM deployment passed host HTTP health check; verify public ALB and database separately')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        prepare(json.loads(Path(sys.argv[1]).read_text()))
    except Exception:
        raise SystemExit('SSM deployment preparation failed; details withheld')
