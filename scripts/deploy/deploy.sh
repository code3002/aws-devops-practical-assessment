#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export AWS_PAGER=""
log() { printf 'app-deploy: %s\n' "$1"; }
trap 'printf "app-deploy: failed at line %s\n" "$LINENO" >&2' ERR
[[ $(uname -s) == Linux && $(uname -m) == x86_64 && $EUID == 0 ]] || exit 1
source /etc/os-release
[[ $ID == amzn && $VERSION_ID == 2023 ]] || exit 1
[[ $# == 4 ]] || { log 'Usage: deploy.sh BUCKET VERSION_ID COMMIT_SHA SHA256'; exit 1; }
bucket=$1 version=$2 revision=$3 digest=$4
[[ $bucket =~ ^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$ && -n $version && $version != null && $revision =~ ^[a-f0-9]{40}$ && $digest =~ ^[a-f0-9]{64}$ ]] || exit 1
readonly root=/opt/assessment
readonly runtime=$root/runtime
[[ -d $root && ! -L $root ]] || exit 1
# All deployment callers must use this host-local lock.
exec 9>"$root/deploy.lock"
flock -n 9 || { log 'Another deployment is running'; exit 1; }
for directory in "$runtime" "$root/releases"; do
  [[ ! -L $directory ]] || exit 1
done
[[ -f $runtime/app.env && ! -L $runtime/app.env && -d $runtime/certs ]] || { log 'Secure runtime configuration and CA directory must exist first'; exit 1; }
[[ $(stat -c '%u:%a' "$runtime/app.env") == 0:600 ]] || { log 'Runtime file must be root-owned mode 0600'; exit 1; }
install -d -o root -g root -m 0750 "$root/releases"
work_dir=$(mktemp -d "$root/.deployment.XXXXXX")
trap 'rm -rf -- "$work_dir"' EXIT
release="$root/releases/${revision}-${digest}"
previous=''
if [[ -L $root/current ]]; then
  previous=$(readlink -f "$root/current")
  [[ $previous == "$root/releases/"* && -d $previous ]] || exit 1
elif [[ -e $root/current ]]; then
  log 'Current must be a managed release symlink'; exit 1
fi
log 'Downloading the approved immutable artifact'
aws s3api get-object --region ap-south-1 --bucket "$bucket" \
  --key "applications/${revision}.tar.gz" --version-id "$version" \
  "$work_dir/artifact.tar.gz" > /dev/null
printf '%s  %s\n' "$digest" "$work_dir/artifact.tar.gz" | sha256sum --check --status
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 "$script_dir/artifact.py" extract "$work_dir/artifact.tar.gz" "$work_dir/release"
if [[ -e $release || -L $release ]]; then
  [[ -d $release && ! -L $release ]] && diff -qr --no-dereference "$work_dir/release" "$release" > /dev/null || {
    log 'Existing release differs from verified artifact'; exit 1;
  }
else
  mv "$work_dir/release" "$release"
fi
compose() {
  local directory=$1
  shift
  # Per-release image tags preserve the previous image for rollback.
  printf '{"services":{"app":{"image":"assessment-app:%s","volumes":["%s/certs:/certs:ro"]}}}\n' \
    "$(basename "$directory")" "$runtime" > "$work_dir/runtime.json"
  docker compose --project-name assessment-app --project-directory "$directory" \
    --env-file "$runtime/app.env" -f "$directory/docker-compose.yml" -f "$work_dir/runtime.json" "$@"
}
healthy() {
  local directory=$1 container service
  for service in app nginx; do
    container=$(compose "$directory" ps -q "$service")
    [[ -n $container ]] || return 1
    [[ $(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container") == "$directory" ]] || return 1
  done
  compose "$directory" exec -T nginx wget -q -O /dev/null http://app:3000/health || return 1
  curl --fail --silent --retry 5 --retry-connrefused --retry-delay 1 --max-time 10 http://127.0.0.1/health > /dev/null
}
compose "$release" config --quiet > "$work_dir/config.log" 2>&1
# Load the image built by CodeBuild; never build application images on EC2.
image_tag="assessment-app:$(basename "$release")"
[[ -n ${IMAGE_VERSION_ID:-} && -n ${IMAGE_SHA256:-} ]] || {
  log 'Verified CodeBuild image details are required'
  exit 1
}

log 'Downloading and verifying the CodeBuild Docker image'
aws s3api get-object --region ap-south-1 --bucket "$bucket" \
  --key "images/${revision}.tar.gz" --version-id "$IMAGE_VERSION_ID" \
  "$work_dir/image.tar.gz" > /dev/null

printf '%s  %s\n' "$IMAGE_SHA256" "$work_dir/image.tar.gz" |
  sha256sum --check --status

docker load -i "$work_dir/image.tar.gz" > /dev/null
docker image inspect "assessment-app:$revision" > /dev/null
docker tag "assessment-app:$revision" "$image_tag"

log 'Starting candidate release'
if compose "$release" up -d --no-build --force-recreate --wait --wait-timeout 120 > "$work_dir/start.log" 2>&1 \
  && healthy "$release"; then
  ln -s "$release" "$work_dir/current"
  mv -Tf "$work_dir/current" "$root/current"
  log 'Deployment passed HTTP health check'
else
  log 'Deployment failed; detailed output withheld to protect runtime values'
  if [[ -n $previous ]]; then
    if compose "$previous" up -d --no-build --force-recreate --wait --wait-timeout 120 > "$work_dir/rollback.log" 2>&1 \
      && healthy "$previous"; then
      log 'Previous release restored'
    else
      log 'Rollback failed; operator intervention required'
    fi
  else
    if compose "$release" down > /dev/null 2>&1; then
      log 'No previous release; candidate containers stopped'
    else
      log 'Candidate cleanup failed; operator intervention required'
    fi
  fi
  exit 1
fi
