#!/usr/bin/env bash
set -Eeuo pipefail

revision="${1:?Usage: upload_image.sh COMMIT_SHA}"
bucket="${2:?Usage: upload_image.sh COMMIT_SHA BUCKET}"

[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || exit 1

archive="assessment-image-${revision}.tar.gz"

[[ -f "$archive" ]] || {
  echo "Image archive not found: $archive" >&2
  exit 1
}

sha256=$(shasum -a 256 "$archive" | awk '{print $1}')

aws s3api put-object \
  --region ap-south-1 \
  --bucket "$bucket" \
  --key "images/${revision}.tar.gz" \
  --body "$archive" \
  --metadata "sha256=$sha256" \
  --query '{VersionId:VersionId,ETag:ETag}' \
  --output json

echo "Uploaded image for commit: $revision"
echo "SHA256: $sha256"
