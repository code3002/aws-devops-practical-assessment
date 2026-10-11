#!/usr/bin/env bash
set -euo pipefail
umask 077
# This installs only inside the disposable Linux CodeBuild environment.
[[ -n "${CODEBUILD_BUILD_ID:-}" && "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  echo 'Terraform installation requires Linux x86_64 CodeBuild' >&2
  exit 1
}
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
  --connect-timeout 15 --max-time 120 \
  https://releases.hashicorp.com/terraform/1.15.8/terraform_1.15.8_linux_amd64.zip \
  --output "$work/terraform.zip"
# Pinned from HashiCorp's official 1.15.8 SHA256SUMS.
printf '%s  %s\n' d25ce7b6902013ad905db3d2eab0be4cd905887fe88b81a6171b8d5503c31f3d "$work/terraform.zip" | sha256sum --check --status
unzip -p "$work/terraform.zip" terraform > "$work/terraform"
chmod 700 "$work/terraform"
"$work/terraform" version -json | python3 -c 'import json,sys; assert json.load(sys.stdin)["terraform_version"] == "1.15.8"'
mkdir -p /tmp/assessment-cleanup-tools
install -m 755 "$work/terraform" /tmp/assessment-cleanup-tools/terraform
