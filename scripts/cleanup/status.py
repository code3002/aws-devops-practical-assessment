"""Read the latest cancellation status; only the trusted controller may write it."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile

import ec2
import record


def load_status(config, source, deployment_record):
    """Get latest cleanup/status/<deployment>.json, never a pinned older version.

    Writer IAM and trusted source delivery are the authority. A timestamp is not
    proof of freshness; unchanged status can legitimately remain enabled for 48h.
    """
    try:
        with tempfile.TemporaryDirectory(prefix='cleanup-status-') as directory:
            path = Path(directory)/'status.json'
            path.touch(mode=0o600)
            ec2.aws(config, 's3api', 'get-object', '--bucket', config['bucket'],
                    '--key', 'cleanup/status/' + config['deployment_id'] + '.json',
                    '--expected-bucket-owner', config['account'], str(path))
            ec2.check(path.stat().st_size <= 65536, 'Control status too large')
            status = json.loads(path.read_bytes(), object_pairs_hook=record.unique_object)
        expected = {
            'version': 1, 'account': config['account'], 'region': config['region'],
            'deployment_id': config['deployment_id'], 'record_bucket': source['bucket'],
            'record_key': source['key'], 'record_version_id': source['version_id'],
            'record_sha256': source['sha256'],
            'configuration_sha256': deployment_record['configuration_sha256'],
        }
        ec2.check(isinstance(status, dict) and set(status) == set(expected) | {'enabled', 'updated_at'}, 'Unexpected control status fields')
        ec2.check(all(type(status[key]) is type(value) and status[key] == value
                      for key, value in expected.items()), 'Control status does not match approved authorization')
        ec2.check(type(status['enabled']) is bool and status['enabled'], 'Teardown canceled or disabled')
        updated = record.timestamp(status['updated_at'])
        ec2.check(record.timestamp(deployment_record['repository_access_granted_at']) <= updated <= datetime.now(timezone.utc), 'Invalid control status update time')
        return status
    except ec2.CleanupError:
        raise
    except (ValueError, KeyError, TypeError, OSError, RecursionError, subprocess.SubprocessError):
        raise ec2.CleanupError('Current control status unavailable or malformed; details withheld') from None
