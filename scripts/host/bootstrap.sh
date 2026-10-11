#!/usr/bin/env bash
set -Eeuo pipefail
umask 022
log() { printf 'host-bootstrap: %s\n' "$1"; }
trap 'printf "host-bootstrap: failed at line %s (exit %s)\n" "$LINENO" "$?" >&2' ERR
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || { log 'Requires Linux x86_64'; exit 1; }
source /etc/os-release
[[ $ID == amzn && $VERSION_ID == 2023 ]] || { log 'Requires Amazon Linux 2023'; exit 1; }
[[ $EUID == 0 ]] || { log 'Run as root on the EC2 host'; exit 1; }
readonly compose_version=2.39.4
readonly compose_sha256=7af95166a730b87e172d4fc9aefea8725d3c6c7327d59149267b452114ddb7d4
readonly plugin=/usr/local/lib/docker/cli-plugins/docker-compose
log 'Installing packages from the AMI-selected AL2023 repository'
dnf install -y docker ca-certificates
if ! command -v curl >/dev/null 2>&1; then
  dnf install -y curl-minimal
fi
if ! rpm -q amazon-ssm-agent >/dev/null 2>&1; then
  dnf install -y amazon-ssm-agent
fi
if [[ ! -f $plugin ]] || ! printf '%s  %s\n' "$compose_sha256" "$plugin" | sha256sum --check --status; then
  work_dir=$(mktemp -d)
  trap 'rm -rf -- "$work_dir"' EXIT
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 \
    --retry 3 --connect-timeout 15 --max-time 180 \
    "https://github.com/docker/compose/releases/download/v${compose_version}/docker-compose-linux-x86_64" \
    --output "$work_dir/docker-compose"
  printf '%s  %s\n' "$compose_sha256" "$work_dir/docker-compose" | sha256sum --check --status
  install -d -o root -g root -m 0755 /usr/local/lib/docker/cli-plugins
  install -o root -g root -m 0755 "$work_dir/docker-compose" "${plugin}.new"
  mv -f -- "${plugin}.new" "$plugin"
fi
systemctl enable --now docker amazon-ssm-agent
for service in docker amazon-ssm-agent; do
  systemctl is-enabled --quiet "$service"
  systemctl is-active --quiet "$service"
done
docker info >/dev/null
[[ $(docker compose version --short) == "$compose_version" ]]
# Preserve an existing deployment directory and all of its contents.
if [[ -L /opt/assessment || ( -e /opt/assessment && ! -d /opt/assessment ) ]]; then
  log 'Application path must be a real directory'; exit 1
fi
if [[ ! -d /opt/assessment ]]; then
  install -d -o root -g root -m 0750 /opt/assessment
fi
log 'Docker, pinned Compose and SSM services verified; application directory ready'
