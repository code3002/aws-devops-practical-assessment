#!/usr/bin/env bash
set -Eeuo pipefail

revision="${1:?Usage: package_image.sh COMMIT_SHA}"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || exit 1

image="assessment-app:$revision"
output="assessment-image-$revision.tar.gz"

docker image inspect "$image" >/dev/null
docker save "$image" | gzip -n > "$output"

echo "Image artifact: $output"
sha256sum "$output"
