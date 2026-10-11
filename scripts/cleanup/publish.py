"""Prepare privately; publish only with reviewed approval and a separate identity.

Initial publication only. Existing control status is never overwritten by default.
No Scheduler or CodeBuild configuration is changed. The approval hash binds the
four exact payloads; the last conditional status write is the authorization commit.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import ec2
import record
import codebuild


def encode(value):
    return json.dumps(value, sort_keys=True).encode()


def prepare(configuration_path, repository_access, ttl=48, retry=2):
    config, inputs = ec2.configuration(configuration_path)
    ec2.check(not config['never_deployed'], 'Deployed state lineage required before publication')
    config = config | {'inputs_file': 'inputs.tfvars.json'}
    start = record.timestamp(repository_access)
    ec2.check(start <= datetime.now(timezone.utc), 'Repository access cannot be in the future')
    ec2.check(type(ttl) is int and ttl > 0 and type(retry) is int and 1 <= retry <= 6, 'Invalid TTL or retry window')
    try:
        deadline = start + timedelta(hours=ttl)
        expires = deadline + timedelta(hours=retry)
    except OverflowError:
        raise ec2.CleanupError('TTL exceeds timestamp range') from None
    utc = lambda value: value.strftime('%Y-%m-%dT%H:%M:%SZ')
    config_hash = record.digest(encode(config))
    deployment_record = dict(version=1, configuration=config, configuration_sha256=config_hash,
                             inputs_sha256=config['inputs_sha256'], repository_access_granted_at=repository_access,
                             TTL_HOURS=ttl, deadline=utc(deadline), enabled=True, retry_hours=retry,
                             authorization=dict(action='DESTROY_EC2_STACK', not_before=utc(deadline), expires_at=utc(expires)))
    record.validate_record(deployment_record, config, inputs, preflight=True)
    authorization = dict(action='DESTROY_EC2_STACK', configuration_sha256=config_hash, expires_at=utc(expires))
    payloads = dict(configuration=encode(config), inputs=inputs, record=encode(deployment_record), authorization=encode(authorization))
    ec2.check(all(len(data) <= 65536 for data in payloads.values()), 'Publication payload too large')
    hashes = {name: record.digest(data) for name, data in payloads.items()}
    return config, payloads, record.digest(encode(hashes))


def publish(config, payloads, bundle_hash, approval_path, publisher_arn):
    ec2.check(not os.environ.get('CODEBUILD_BUILD_ID'), 'CodeBuild executor cannot publish authorization')
    ec2.check(set(payloads) == {'configuration', 'inputs', 'record', 'authorization'} and
              payloads['configuration'] == encode(config) and
              record.digest(encode({name: record.digest(data) for name, data in payloads.items()})) == bundle_hash, 'Prepared publication changed')
    deployment_record = json.loads(payloads['record'], object_pairs_hook=record.unique_object)
    record.validate_record(deployment_record, config, payloads['inputs'], preflight=True)
    authorization = json.loads(payloads['authorization'], object_pairs_hook=record.unique_object)
    ec2.check(authorization == dict(action='DESTROY_EC2_STACK',
              configuration_sha256=deployment_record['configuration_sha256'],
              expires_at=deployment_record['authorization']['expires_at']), 'Publication authorization mismatch')
    approval = json.loads(Path(approval_path).read_bytes(), object_pairs_hook=record.unique_object)
    ec2.check(set(approval) == {'action', 'bundle_sha256', 'publisher_arn', 'expires_at'} and
              approval['action'] == 'PUBLISH_EC2_TEARDOWN' and approval['bundle_sha256'] == bundle_hash and
              approval['publisher_arn'] == publisher_arn, 'Publication approval scope mismatch')
    ec2.check(record.timestamp(approval['expires_at']) > datetime.now(timezone.utc), 'Publication approval expired')
    caller = ec2.aws(config, 'sts', 'get-caller-identity')
    ec2.check(caller['Account'] == config['account'] and caller['Arn'] == publisher_arn and
              ':assumed-role/' + config['deployment_id'] + '-build/' not in caller['Arn'], 'Trusted publisher identity required')
    ec2.source_files(config)
    owner = ['--expected-bucket-owner', config['account']]
    ec2.check(ec2.aws(config, 's3api', 'get-bucket-location', '--bucket', config['bucket'], *owner)['LocationConstraint'] == config['region'], 'Publication bucket region mismatch')
    ec2.check(ec2.aws(config, 's3api', 'get-bucket-versioning', '--bucket', config['bucket'], *owner).get('Status') == 'Enabled', 'Versioned bucket required')
    block = ec2.aws(config, 's3api', 'get-public-access-block', '--bucket', config['bucket'], *owner)['PublicAccessBlockConfiguration']
    ec2.check(all(block.get(key) is True for key in ['BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets']), 'Private publication bucket required')
    ec2.check(ec2.aws(config, 's3api', 'get-bucket-policy-status', '--bucket', config['bucket'], *owner)['PolicyStatus']['IsPublic'] is False, 'Public bucket policy forbidden')
    status_key = 'cleanup/status/' + config['deployment_id'] + '.json'
    delivery = {}
    with tempfile.TemporaryDirectory(prefix='cleanup-publish-') as directory:
        work = Path(directory)
        state_path = work/'state.json'; state_path.touch(mode=0o600)
        ec2.aws(config, 's3api', 'get-object', '--bucket', config['bucket'], '--key', config['key'], *owner, str(state_path))
        ec2.check(bool(ec2.state_resources(config, json.loads(state_path.read_bytes()))), 'Deployment state is empty')
        def put(key, data, condition):
            path = work/'payload.json'; path.touch(mode=0o600); path.write_bytes(data)
            return ec2.aws(config, 's3api', 'put-object', '--bucket', config['bucket'], '--key', key,
                           '--body', str(path), '--server-side-encryption', 'AES256', '--content-type', 'application/json', *owner, *condition)
        # A pending marker cannot pass the strict executor status validator.
        pending = put(status_key, encode({'enabled': False, 'deployment_id': config['deployment_id'],
                      'publication': 'PENDING', 'attempt': str(uuid.uuid4())}), ['--if-none-match', '*'])
        ec2.check(isinstance(pending.get('ETag'), str) and bool(pending['ETag']), 'Pending status acknowledgement missing')
        groups = {'configuration': 'config', 'inputs': 'inputs', 'record': 'records', 'authorization': 'authorizations'}
        for name, group in groups.items():
            key = f"cleanup/{group}/{config['deployment_id']}.json"
            result = put(key, payloads[name], [])
            version = result.get('VersionId')
            ec2.check(isinstance(version, str) and bool(version) and version != 'null', 'Immutable publication version missing')
            delivery[name] = dict(bucket=config['bucket'], key=key, version_id=version, sha256=record.digest(payloads[name]))
            codebuild.download(delivery[name], config, key, work/'verify.json')
        # Expiry may have passed during uploads. Leave PENDING on any rejection.
        record.validate_record(deployment_record, config, payloads['inputs'], preflight=True)
        ec2.check(record.timestamp(approval['expires_at']) > datetime.now(timezone.utc), 'Publication approval expired')
        source = delivery['record']
        enabled = dict(version=1, account=config['account'], region=config['region'], deployment_id=config['deployment_id'],
                       record_bucket=source['bucket'], record_key=source['key'], record_version_id=source['version_id'],
                       record_sha256=source['sha256'], configuration_sha256=deployment_record['configuration_sha256'],
                       enabled=True, updated_at=datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
        try:
            put(status_key, encode(enabled), ['--if-match', pending['ETag']])
        except (ec2.CleanupError, OSError, subprocess.SubprocessError):
            raise ec2.CleanupError('Final status write not acknowledged; inspect latest status before retrying') from None
    return delivery


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('configuration')
    parser.add_argument('--repository-access', required=True, help='Authoritative repository access grant instant, UTC')
    parser.add_argument('--ttl-hours', type=int, default=48)
    parser.add_argument('--retry-hours', type=int, default=2)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--approval')
    parser.add_argument('--publisher-arn')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config, payloads, bundle_hash = prepare(args.configuration, args.repository_access, args.ttl_hours, args.retry_hours)
        if args.publish:
            ec2.check(args.approval and args.publisher_arn, 'Explicit publication approval and identity required')
            print(json.dumps(publish(config, payloads, bundle_hash, args.approval, args.publisher_arn), sort_keys=True))
        else:
            print(json.dumps({'mode': 'DRY_RUN', 'bundle_sha256': bundle_hash,
                              'payload_sha256': {key: record.digest(value) for key, value in payloads.items()}}, sort_keys=True))
    except ec2.CleanupError as error:
        raise SystemExit('Publication stopped: ' + str(error))
    except (ValueError, KeyError, TypeError, OSError, RecursionError, subprocess.SubprocessError):
        raise SystemExit('Publication stopped: configuration or command failure; details withheld')
