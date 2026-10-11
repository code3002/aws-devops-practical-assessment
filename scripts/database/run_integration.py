"""Optional isolated Docker integration test. Never reads AWS credentials or publishes ports."""
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid
import urllib.request
import configure


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError('Local test command failed: ' + args[0] + '\n' + result.stdout + result.stderr)
    return result.stdout


def main():
    name = 'assessment-db-test-' + uuid.uuid4().hex[:10]
    here = Path(__file__).resolve().parent
    # Compare only identifiers and start times; do not inspect website environment values.
    before = run(['docker', 'inspect', '--format', '{{.Id}} {{.State.StartedAt}}',
                  'assessment-review-app-1', 'assessment-review-nginx-1'])
    with tempfile.TemporaryDirectory(prefix='assessment-db-') as temporary:
        fixture = Path(temporary); fixture.chmod(0o755)
        passwords = {key: secrets.token_urlsafe(32) for key in ['rootPassword', 'adminPassword', 'appPassword']}
        password_file = fixture/'root.password'; password_file.write_text(passwords['rootPassword']); password_file.chmod(0o600)
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
             '-subj', '/CN=Local test CA', '-keyout', str(fixture/'ca.key'), '-out', str(fixture/'rds-ca.pem')])
        run(['openssl', 'req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=testpg',
             '-keyout', str(fixture/'server.key'), '-out', str(fixture/'server.csr')])
        (fixture/'extensions').write_text('subjectAltName=DNS:testpg\nextendedKeyUsage=serverAuth\n')
        run(['openssl', 'x509', '-req', '-in', str(fixture/'server.csr'), '-CA', str(fixture/'rds-ca.pem'),
             '-CAkey', str(fixture/'ca.key'), '-CAcreateserial', '-days', '1', '-extfile', str(fixture/'extensions'),
             '-out', str(fixture/'server.crt')])
        network_created = False
        compose_args = None
        try:
            run(['docker', 'network', 'create', name]); network_created = True
            run(['docker', 'run', '-d', '--name', name, '--network', name, '--network-alias', 'testpg', '--network-alias', 'wrong-host',
                 '-v', str(fixture)+':/fixture:ro', '-e', 'POSTGRES_USER=fixture_root', '-e', 'POSTGRES_DB=assessment',
                 '-e', 'POSTGRES_PASSWORD_FILE=/fixture/root.password', '--entrypoint', 'sh', 'postgres:17.1-alpine', '-c',
                 'mkdir /tmp/tls && cp /fixture/server.key /fixture/server.crt /tmp/tls/ && chown -R postgres:postgres /tmp/tls && chmod 600 /tmp/tls/server.key && exec docker-entrypoint.sh postgres -c ssl=on -c ssl_cert_file=/tmp/tls/server.crt -c ssl_key_file=/tmp/tls/server.key'])
            for _ in range(60):
                ready = subprocess.run(['docker', 'exec', name, 'pg_isready', '-U', 'fixture_root', '-d', 'assessment'], capture_output=True)
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError('Temporary PostgreSQL did not become ready')
            result = run(['docker', 'run', '--rm', '-i', '--network', name, '--read-only', '--cap-drop', 'ALL',
                          '-v', str(here)+':/integration:ro', '-v', str(fixture)+':/certs:ro',
                          '--entrypoint', 'node', 'assessment-review-app', '/integration/integration.cjs'],
                         input=json.dumps(passwords))
            print(result.strip())
            runtime_file = fixture/'app.env'
            runtime_file.write_text(configure.runtime_text('testpg', passwords['appPassword']))
            runtime_file.chmod(0o600)
            override = fixture/'override.json'
            override.write_text(json.dumps({'services': {'app': {'image': 'assessment-review-app', 'volumes': [str(fixture)+':/certs:ro']}}, 'networks': {'default': {'external': True, 'name': name}}}))
            ports = fixture/'ports.yml'
            ports.write_text('services:\n  nginx:\n    ports: !override ["127.0.0.1:18086:80"]\n')
            repository = here.parents[1]
            compose_args = ['docker', 'compose', '-p', name, '--project-directory', str(repository), '--env-file', str(runtime_file), '-f', str(repository/'docker-compose.yml'), '-f', str(override), '-f', str(ports)]
            effective = json.loads(run(compose_args + ['config', '--format', 'json']))
            app_config = effective['services']['app']
            assert app_config['environment']['PGSSLMODE'] == 'verify-full'
            assert app_config['environment']['PGPASSWORD'] == passwords['appPassword']
            assert 'ports' not in app_config
            run(compose_args + ['up', '-d', '--no-build', '--wait', '--wait-timeout', '60'])
            request = urllib.request.Request('http://127.0.0.1:18086/messages', data=json.dumps({'text': 'Compose TLS database check'}).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=10) as response:
                assert response.status == 201
                assert json.load(response)['text'] == 'Compose TLS database check'
            print('PASS: existing Compose app through isolated Nginx HTTP 201, real PostgreSQL insert/read with verified TLS; runtime file mode 0600')
        finally:
            if compose_args:
                subprocess.run(compose_args + ['down'], capture_output=True)
            subprocess.run(['docker', 'rm', '-f', '-v', name], capture_output=True)
            if network_created:
                subprocess.run(['docker', 'network', 'rm', name], capture_output=True)
    after = run(['docker', 'inspect', '--format', '{{.Id}} {{.State.StartedAt}}',
                 'assessment-review-app-1', 'assessment-review-nginx-1'])
    if before != after:
        raise RuntimeError('Review website changed')
    print('PASS: temporary resources removed; review website unchanged')


if __name__ == '__main__':
    main()
