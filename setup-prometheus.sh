#!/usr/bin/env bash
set -euo pipefail

# Run from the repository root, on feature/cloudwatch-sns-monitoring.
if [[ ! -f docker-compose.yml || ! -f nginx/default.conf ]]; then
  echo 'ERROR: Run from the repository root (docker-compose.yml and nginx/default.conf required).' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'ERROR: python3 is required.' >&2
  exit 1
fi

python3 - <<'PY'
from pathlib import Path
import sys

compose_path = Path('docker-compose.yml')
nginx_path = Path('nginx/default.conf')
prom_path = Path('monitoring/prometheus.yml')
compose = compose_path.read_text()
nginx = nginx_path.read_text()

# Fail closed if the repository differs from the supplied baseline.
if '  app:\n' not in compose or '  nginx:\n' not in compose or 'services:\n' not in compose:
    sys.exit('ERROR: Unexpected Compose structure; no files changed.')
if '    ports: ["80:80"]' not in compose:
    sys.exit('ERROR: Expected Nginx port mapping not found; no files changed.')
if 'server {\n' not in nginx or 'proxy_pass http://app:3000;' not in nginx:
    sys.exit('ERROR: Unexpected Nginx configuration; no files changed.')
if 'node-exporter:' in compose or 'nginx-exporter:' in compose or '\n  prometheus:' in compose:
    sys.exit('ERROR: Monitoring services already present; inspect existing files instead.')
if 'listen 8080;' in nginx or 'stub_status;' in nginx:
    sys.exit('ERROR: Nginx status endpoint already present; inspect existing config.')
if prom_path.exists():
    sys.exit('ERROR: monitoring/prometheus.yml already exists; inspect rather than overwrite.')

# The second server is reachable only on the Compose network; port 8080 is not published.
status_server = '''\n# Internal-only endpoint for nginx-prometheus-exporter; do not publish port 8080.\nserver {\n    listen 8080;\n    server_tokens off;\n    location = /stub_status {\n        stub_status;\n        access_log off;\n        allow 127.0.0.1;\n        allow 172.16.0.0/12;\n        allow 192.168.0.0/16;\n        allow 10.0.0.0/8;\n        deny all;\n    }\n    location / { return 404; }\n}\n'''

services = '''\n  node-exporter:\n    image: prom/node-exporter:v1.9.1\n    restart: unless-stopped\n    command:\n      - '--path.rootfs=/host'\n    pid: host\n    volumes:\n      - '/:/host:ro,rslave'\n    expose:\n      - '9100'\n\n  nginx-exporter:\n    image: nginx/nginx-prometheus-exporter:1.4.2\n    restart: unless-stopped\n    command:\n      - '--nginx.scrape-uri=http://nginx:8080/stub_status'\n    depends_on:\n      - nginx\n    expose:\n      - '9113'\n\n  prometheus:\n    image: prom/prometheus:v3.5.0\n    restart: unless-stopped\n    command:\n      - '--config.file=/etc/prometheus/prometheus.yml'\n      - '--storage.tsdb.path=/prometheus'\n      - '--storage.tsdb.retention.time=7d'\n    volumes:\n      - './monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro'\n      - 'prometheus_data:/prometheus'\n    ports:\n      - '127.0.0.1:9090:9090'\n    depends_on:\n      - node-exporter\n      - nginx-exporter\n\nvolumes:\n  prometheus_data:\n'''

prometheus = '''global:\n  scrape_interval: 15s\n\nscrape_configs:\n  - job_name: node_exporter\n    static_configs:\n      - targets: ['node-exporter:9100']\n\n  - job_name: nginx_exporter\n    static_configs:\n      - targets: ['nginx-exporter:9113']\n'''

# Write only after all checks have passed.
nginx_path.write_text(nginx.rstrip() + '\n' + status_server)
compose_path.write_text(compose.rstrip() + '\n' + services)
prom_path.parent.mkdir(exist_ok=True)
prom_path.write_text(prometheus)
print('Updated docker-compose.yml and nginx/default.conf; created monitoring/prometheus.yml')
PY

echo
echo '=== Changes ==='
git diff -- docker-compose.yml nginx/default.conf || true
echo
echo '=== Files ==='
git status --short
echo
echo 'Next: review changes; on a machine with Docker Compose and PG* variables set, run:'
echo '  docker compose config --quiet'
echo '  docker compose up -d --build'
echo '  curl -fsS http://127.0.0.1:9090/api/v1/query?query=up'
echo 'NOTE: The script does not deploy or change AWS resources.'
