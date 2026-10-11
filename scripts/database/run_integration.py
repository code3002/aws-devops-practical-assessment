"""Optional isolated Docker integration test. Uses generated test secrets and a temporary loopback-only HTTP port."""
import json
from pathlib import Path
import secrets
import subprocess
import tempfile
import time
import uuid
import urllib.request
import urllib.error
import configure


def run(args, **kwargs):
    result = subprocess.run(args, capture_output=True, text=True, **kwargs)
    if result.returncode:
        raise RuntimeError('Local test command failed: ' + args[0] + '; output withheld')
    return result.stdout


def check_response(request, expected):
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status in (expected if isinstance(expected, tuple) else (expected,)), f"Expected {expected}, got {response.status}"
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert response.headers['X-XSS-Protection'] == '1; mode=block'
        assert "default-src 'self'" in response.headers['Content-Security-Policy']
        assert '*' not in response.headers['Content-Security-Policy']
        assert 'Strict-Transport-Security' not in response.headers  # HTTP-only scope
        if isinstance(expected, tuple): print(f'PASS: Nginx upstream failure HTTP {response.status} has required headers')
        return response.read()


def cleanup(compose_args, name, network_created):
    commands = ([compose_args + ['down']] if compose_args else [])
    commands += [['docker', 'rm', '-f', '-v', name]]
    if network_created:
        commands += [['docker', 'network', 'rm', name]]
    failed = False
    for command in commands:
        result = subprocess.run(command, capture_output=True, text=True)
        failed = failed or result.returncode != 0
    if failed:
        raise RuntimeError('Temporary resource cleanup failed; output withheld')


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
            assert json.loads(check_response(request, 201))['text'] == 'Compose TLS database check'
            base = 'http://127.0.0.1:18086'
            check_response(base + '/', 200)
            check_response(base + '/missing', 404)
            first = json.loads(check_response(base + '/time', 200))['timestamp']
            time.sleep(0.02)
            assert json.loads(check_response(base + '/time', 200))['timestamp'] != first
            for text, status in [('', 400), ('x' * 5000, 413)]:
                check_response(urllib.request.Request(base + '/messages', data=json.dumps({'text': text}).encode(), headers={'Content-Type': 'application/json'}), status)
            run(['docker', 'stop', name])
            check_response(request, 503)
            run(compose_args + ['stop', 'app'])
            check_response(base + '/health', (502, 504))
            print('PASS: changing time and Nginx headers on HTTP 200/201/400/404/413/503 and upstream failure; HSTS absent in HTTP-only scope')
            print('PASS: existing Compose app through isolated Nginx HTTP 201, real PostgreSQL insert/read with verified TLS; runtime file mode 0600')
        finally:
            cleanup(compose_args, name, network_created)
    after = run(['docker', 'inspect', '--format', '{{.Id}} {{.State.StartedAt}}',
                 'assessment-review-app-1', 'assessment-review-nginx-1'])
    if before != after:
        raise RuntimeError('Review website changed')
    print('PASS: temporary resources removed; review website unchanged')


if __name__ == '__main__':
    main()
