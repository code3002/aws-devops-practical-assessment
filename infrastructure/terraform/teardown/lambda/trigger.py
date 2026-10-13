"""TTL trigger (brief §6): EventBridge Scheduler invokes this at the deadline and
it starts the CodeBuild destroy project. It never destroys anything itself.

Manual use: `aws lambda invoke --function-name <name> --payload '{"force": true}'`
starts the project before the deadline (EXECUTION_MODE still applies).
"""
from datetime import datetime, timezone
import json
import os

import boto3

# Tolerate scheduler clock skew and retries shortly before the deadline.
EARLY_TOLERANCE_SECONDS = 300


def deadline():
    return datetime.strptime(os.environ["DEADLINE"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def handler(event, _context, client=None, now=None):
    event = event if isinstance(event, dict) else {}
    now = now or datetime.now(timezone.utc)
    remaining = (deadline() - now).total_seconds()
    if remaining > EARLY_TOLERANCE_SECONDS and event.get("force") is not True:
        result = {"started": False, "reason": "deadline not reached", "deadline": os.environ["DEADLINE"]}
        print(json.dumps(result))
        return result
    client = client or boto3.client("codebuild")
    build = client.start_build(
        projectName=os.environ["PROJECT_NAME"],
        environmentVariablesOverride=[
            {"name": "TRIGGERED_BY", "value": "manual" if event.get("force") is True else "scheduler", "type": "PLAINTEXT"},
            {"name": "TEARDOWN_DEADLINE", "value": os.environ["DEADLINE"], "type": "PLAINTEXT"},
        ],
    )["build"]
    result = {"started": True, "build_id": build["id"]}
    print(json.dumps(result))
    return result
