#!/usr/bin/env bash
set -euo pipefail
# No xtrace or environment dumps: temporary credentials/state must stay private.
export AWS_PAGER="" AWS_RETRY_MODE=standard AWS_MAX_ATTEMPTS=3
executor_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python3 "$executor_dir/preflight.py"
