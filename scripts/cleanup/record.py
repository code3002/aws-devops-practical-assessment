"""Read a pinned deployment record; never authorize, schedule, or execute cleanup.

The caller must obtain the source coordinates and SHA-256 from the approved
deployment process. An old immutable record cannot establish current cancellation
status: integration must also check the current control record before destruction.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

import ec2


def digest(data):
    return hashlib.sha256(data).hexdigest()


def timestamp(value):
    ec2.check(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', value), 'Invalid UTC timestamp')
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ec2.CleanupError('Invalid UTC timestamp') from None


def validate_record(record, config, inputs):
    fields = {'version', 'configuration', 'configuration_sha256', 'inputs_sha256',
              'repository_access_granted_at', 'TTL_HOURS', 'deadline', 'enabled',
              'retry_hours', 'authorization'}
    ec2.check(isinstance(record, dict) and set(record) == fields, 'Unexpected deployment record fields')
    ec2.check(type(record['version']) is int and record['version'] == 1, 'Unsupported record version')
    retained = record['configuration']
    ec2.check(isinstance(retained, dict) and set(retained) == set(config) and
              all(type(retained[key]) is type(value) and retained[key] == value
                  for key, value in config.items()), 'Deployment configuration mismatch')
    # Match the existing executor's configuration hash convention exactly.
    expected = digest(json.dumps(retained, sort_keys=True).encode())
    ec2.check(record['configuration_sha256'] == expected, 'Configuration hash mismatch')
    ec2.check(record['inputs_sha256'] == config['inputs_sha256'] == digest(inputs), 'Retained input hash mismatch')
    ec2.check(type(record['enabled']) is bool and record['enabled'], 'Deployment canceled or not enabled')
    ttl, retry = record['TTL_HOURS'], record['retry_hours']
    ec2.check(type(ttl) is int and ttl > 0, 'TTL_HOURS must be a positive integer')
    ec2.check(type(retry) is int and 1 <= retry <= 6, 'Retry window must be 1-6 hours')
    start, deadline = timestamp(record['repository_access_granted_at']), timestamp(record['deadline'])
    try:
        ec2.check(deadline == start + timedelta(hours=ttl), 'Deadline does not match repository access plus TTL')
        end = deadline + timedelta(hours=retry)
    except OverflowError:
        raise ec2.CleanupError('TTL exceeds timestamp range') from None
    authorization = record['authorization']
    ec2.check(isinstance(authorization, dict) and set(authorization) == {'action', 'not_before', 'expires_at'}, 'Unexpected authorization fields')
    ec2.check(authorization['action'] == 'DESTROY_EC2_STACK', 'Authorization scope mismatch')
    ec2.check(timestamp(authorization['not_before']) == deadline and timestamp(authorization['expires_at']) == end, 'Authorization window mismatch')
    now = datetime.now(timezone.utc)
    ec2.check(deadline <= now, 'Cleanup cannot start before the deadline')
    ec2.check(now < end, 'Authorization expired; retry window closed')
    return record


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        ec2.check(key not in result, 'Duplicate JSON field')
        result[key] = value
    return result


def load_record(source, configuration_path):
    """Read one approved S3 version and compare it with retained local inputs.

    source: bucket, key, version_id, sha256. No latest-version fallback is allowed.
    Configuration/inputs are read using the existing executor's strict validator.
    No AWS call runs until both the local configuration and source are validated.
    """
    try:
        return _load_record(source, configuration_path)
    except ec2.CleanupError:
        raise
    except (ValueError, KeyError, TypeError, OSError, RecursionError, subprocess.SubprocessError):
        raise ec2.CleanupError('Deployment record load failed; details withheld') from None


def _load_record(source, configuration_path):
    config, inputs = ec2.configuration(configuration_path)
    ec2.check(isinstance(source, dict) and set(source) == {'bucket', 'key', 'version_id', 'sha256'}, 'Unexpected record source')
    ec2.check(source['bucket'] == config['bucket'] and source['key'] == 'cleanup/records/' + config['deployment_id'] + '.json', 'Unapproved record location')
    version = source['version_id']
    ec2.check(isinstance(version, str) and 0 < len(version) <= 1024 and version != 'null' and not any(c.isspace() for c in version) and not version.startswith('-'), 'Explicit immutable S3 version required')
    ec2.check(isinstance(source['sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', source['sha256']), 'Trusted record hash required')
    ec2.check(ec2.aws(config, 'sts', 'get-caller-identity')['Account'] == config['account'], 'AWS account mismatch')
    with tempfile.TemporaryDirectory(prefix='cleanup-record-') as directory:
        path = Path(directory)/'record.json'
        path.touch(mode=0o600)
        metadata = ec2.aws(config, 's3api', 'get-object', '--bucket', source['bucket'],
                           '--key', source['key'], '--version-id', version,
                           '--expected-bucket-owner', config['account'], str(path))
        ec2.check(metadata.get('VersionId') == version, 'Record version mismatch')
        ec2.check(path.stat().st_size <= 65536, 'Deployment record too large')
        data = path.read_bytes()
        ec2.check(digest(data) == source['sha256'], 'Deployment record hash mismatch')
        try:
            record = json.loads(data, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError):
            raise ec2.CleanupError('Invalid deployment record JSON') from None
        return validate_record(record, config, inputs)
