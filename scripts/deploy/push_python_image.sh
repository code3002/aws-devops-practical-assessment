#!/usr/bin/env bash
# Build the EKS Python image and push it to ECR as <commit-sha> and latest.
# Runs in CodeBuild after the EC2 deployment so ECR issues never block the EC2 path.
set -Eeuo pipefail

revision="${CODEBUILD_RESOLVED_SOURCE_VERSION:?Missing source revision}"
[[ "$revision" =~ ^[a-f0-9]{40}$ ]] || {
  echo "Expected a 40-character Git commit SHA" >&2
  exit 1
}
: "${PYTHON_IMAGE_REPOSITORY:?}"
: "${AWS_DEFAULT_REGION:?}"

registry="${PYTHON_IMAGE_REPOSITORY%%/*}"
aws ecr get-login-password --region "$AWS_DEFAULT_REGION" |
  docker login --username AWS --password-stdin "$registry"

docker build -t "$PYTHON_IMAGE_REPOSITORY:$revision" apps/python-time
docker tag "$PYTHON_IMAGE_REPOSITORY:$revision" "$PYTHON_IMAGE_REPOSITORY:latest"
docker push "$PYTHON_IMAGE_REPOSITORY:$revision"
docker push "$PYTHON_IMAGE_REPOSITORY:latest"
echo "Pushed $PYTHON_IMAGE_REPOSITORY:$revision"
