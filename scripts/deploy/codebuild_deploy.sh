#!/usr/bin/env bash
set -Eeuo pipefail

revision="${CODEBUILD_RESOLVED_SOURCE_VERSION:?Missing source revision}"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || {
  echo "Expected a 40-character Git commit SHA" >&2
  exit 1
}

: "${ARTIFACT_BUCKET:?}"
: "${EC2_INSTANCE_ID:?}"
: "${DEPLOYMENT_DOCUMENT:?}"
: "${EXPECTED_ACCOUNT_ID:?}"
: "${AWS_DEFAULT_REGION:?}"
: "${DATABASE_HOST:?}"
: "${ADMIN_SECRET_ARN:?}"
: "${APP_SECRET_ARN:?}"
: "${RDS_CA_SHA256:?}"

work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT

echo "Packaging source artifact"
source_archive="$work_dir/source.tar.gz"
python3 scripts/deploy/artifact.py package "$revision" "$source_archive"

echo "Packaging Docker image"
image_archive="$work_dir/image.tar.gz"
docker save "assessment-app:$revision" | gzip -n > "$image_archive"

echo "Uploading immutable artifacts"
aws s3api put-object \
  --region "$AWS_DEFAULT_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  --key "applications/$revision.tar.gz" \
  --body "$source_archive" \
  --query VersionId --output text > "$work_dir/source-version"

aws s3api put-object \
  --region "$AWS_DEFAULT_REGION" \
  --bucket "$ARTIFACT_BUCKET" \
  --key "images/$revision.tar.gz" \
  --body "$image_archive" \
  --query VersionId --output text > "$work_dir/image-version"

export SOURCE_VERSION_ID
SOURCE_VERSION_ID=$(cat "$work_dir/source-version")

export IMAGE_VERSION_ID
IMAGE_VERSION_ID=$(cat "$work_dir/image-version")

export SOURCE_SHA256
SOURCE_SHA256=$(sha256sum "$source_archive" | awk '{print $1}')

export IMAGE_SHA256
IMAGE_SHA256=$(sha256sum "$image_archive" | awk '{print $1}')

echo "Preparing SSM deployment configuration"
python3 - "$revision" "$work_dir/configuration.txt" <<'PY'
import base64
import json
import os
import sys

revision, destination = sys.argv[1:]

config = {
    "account": os.environ["EXPECTED_ACCOUNT_ID"],
    "region": os.environ["AWS_DEFAULT_REGION"],
    "host": os.environ["DATABASE_HOST"],
    "admin_secret_arn": os.environ["ADMIN_SECRET_ARN"],
    "app_secret_arn": os.environ["APP_SECRET_ARN"],
    "ca_sha256": os.environ["RDS_CA_SHA256"],
    "bucket": os.environ["ARTIFACT_BUCKET"],
    "version_id": os.environ["SOURCE_VERSION_ID"],
    "revision": revision,
    "artifact_sha256": os.environ["SOURCE_SHA256"],
    "image_version_id": os.environ["IMAGE_VERSION_ID"],
    "image_sha256": os.environ["IMAGE_SHA256"],
    "initialize": False,
}

encoded = base64.b64encode(
    json.dumps(config, separators=(",", ":")).encode()
).decode()

with open(destination, "w", encoding="ascii") as output:
    output.write(encoded)
PY

echo "Deploying commit $revision through SSM"
command_id=$(aws ssm send-command \
  --region "$AWS_DEFAULT_REGION" \
  --document-name "$DEPLOYMENT_DOCUMENT" \
  --instance-ids "$EC2_INSTANCE_ID" \
  --parameters "$(python3 -c 'import json,sys; print(json.dumps({"Configuration": [open(sys.argv[1]).read()]}))' "$work_dir/configuration.txt")" \
  --query 'Command.CommandId' \
  --output text)

echo "Waiting for SSM command: $command_id"

deadline=$((SECONDS + 1500))

while (( SECONDS < deadline )); do
  status=$(aws ssm get-command-invocation \
    --region "$AWS_DEFAULT_REGION" \
    --command-id "$command_id" \
    --instance-id "$EC2_INSTANCE_ID" \
    --query Status --output text 2>/dev/null) || status="Pending"

  case "$status" in
    Success)
      echo "Deployment successful: $revision"
      exit 0
      ;;
    Failed|Cancelled|TimedOut|Cancelling)
      echo "Deployment failed: $status" >&2
      aws ssm get-command-invocation \
        --region "$AWS_DEFAULT_REGION" \
        --command-id "$command_id" \
        --instance-id "$EC2_INSTANCE_ID" \
        --query '{Status:Status,Details:StatusDetails,ResponseCode:ResponseCode}' \
        --output json >&2 || true
      exit 1
      ;;
    Pending|InProgress|Delayed)
      echo "Deployment status: $status"
      ;;
    *)
      echo "Unexpected SSM status: $status" >&2
      exit 1
      ;;
  esac

  sleep 15
done

echo "Deployment polling timed out after 25 minutes: $command_id" >&2
exit 1
