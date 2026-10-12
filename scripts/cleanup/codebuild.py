"""CodeBuild entry point. References are trusted project inputs, never credentials.

CLEANUP_DELIVERY is JSON with configuration, inputs, record, and (only for
destruction) authorization S3 references: bucket, key, version_id, sha256.
The retained configuration must use inputs_file="inputs.tfvars.json" so it is
portable without changing the approved configuration hash.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import ec2
import eks
import kubernetes
import record
import status


def download(source, config, key, destination):
    ec2.check(isinstance(source, dict) and set(source) == {'bucket', 'key', 'version_id', 'sha256'}, 'Unexpected delivery reference')
    ec2.check(source['bucket'] == config['bucket'] and source['key'] == key, 'Unapproved delivery location')
    version = source['version_id']
    ec2.check(isinstance(version, str) and 0 < len(version) <= 1024 and version != 'null' and not version.startswith('-') and not any(c.isspace() for c in version), 'Explicit delivery version required')
    ec2.check(isinstance(source['sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', source['sha256']), 'Trusted delivery hash required')
    destination.touch(mode=0o600)
    metadata = ec2.aws(config, 's3api', 'get-object', '--bucket', source['bucket'], '--key', key,
                       '--version-id', version, '--expected-bucket-owner', config['account'], str(destination))
    ec2.check(metadata.get('VersionId') == version and destination.stat().st_size <= 65536, 'Delivery version or size mismatch')
    ec2.check(record.digest(destination.read_bytes()) == source['sha256'], 'Delivery hash mismatch')


def run():
    mode = os.environ.get('EXECUTION_MODE', 'PREFLIGHT_ONLY')
    ec2.check(mode in {'PREFLIGHT_ONLY', 'DESTROY_FULL_STACK'}, 'Unsupported execution mode')
    execute = mode == 'DESTROY_FULL_STACK'
    account, region = os.environ['EXPECTED_ACCOUNT_ID'], os.environ['AWS_REGION']
    deployment, sha = os.environ['DEPLOYMENT_ID'], os.environ['EXPECTED_SOURCE_COMMIT']
    bucket = os.environ['BACKEND_BUCKET']
    ec2.check(re.fullmatch(r'\d{12}', account) and region == 'ap-south-1', 'Invalid build identity')
    ec2.check(re.fullmatch(r'[a-z][a-z0-9-]{2,39}', deployment) and re.fullmatch(r'[a-f0-9]{40}', sha), 'Invalid deployment or source')
    ec2.check(re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', bucket), 'Invalid backend bucket')
    ec2.check(os.environ.get('CODEBUILD_RESOLVED_SOURCE_VERSION') == sha and
              ec2.command(['git', '-C', str(ec2.ROOT), 'rev-parse', 'HEAD']).strip() == sha, 'CodeBuild source mismatch')
    ec2.check(json.loads(ec2.command(['terraform', 'version', '-json']))['terraform_version'] == '1.15.8', 'Pinned Terraform 1.15.8 required')
    delivery = json.loads(os.environ['CLEANUP_DELIVERY'], object_pairs_hook=record.unique_object)
    fields = {'configuration', 'inputs', 'record'} | ({'authorization'} if execute else set())
    ec2.check(isinstance(delivery, dict) and set(delivery) == fields, 'Required trusted delivery references missing or unexpected')
    identity = dict(account=account, region=region, bucket=bucket)
    ec2.check(ec2.aws(identity, 'sts', 'get-caller-identity')['Account'] == account, 'AWS account mismatch')
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='cleanup-build-') as directory:
        work = Path(directory)
        download(delivery['configuration'], identity, f'cleanup/config/{deployment}.json', work/'config.json')
        download(delivery['inputs'], identity, f'cleanup/inputs/{deployment}.json', work/'inputs.tfvars.json')
        retained = json.loads((work/'config.json').read_bytes(), object_pairs_hook=record.unique_object)
        ec2.check(isinstance(retained, dict) and retained.get('inputs_file') == 'inputs.tfvars.json', 'Portable retained inputs filename required')
        try:
            os.chdir(work)
            config, inputs = ec2.configuration(work/'config.json')
            ec2.check(config['account'] == account and config['region'] == region and config['deployment_id'] == deployment and
                      config['bucket'] == bucket and config['source_sha'] == sha and config['inputs_file'] == 'inputs.tfvars.json', 'Retained build configuration mismatch')
            deployment_record = record.load_record(delivery['record'], work/'config.json', preflight=not execute)
            status.load_status(config, delivery['record'], deployment_record)
            approval = None
            if execute:
                approval = work/'authorization.json'
                download(delivery['authorization'], identity, f'cleanup/authorizations/{deployment}.json', approval)
            cluster = os.environ.get('EKS_CLUSTER_NAME')
            if execute:
                ec2.check(cluster is not None, 'Full destroy requires explicit EKS inputs')
            if cluster:
                if execute:
                    ec2.check(os.environ.get('FULL_DESTROY_IAM_READY') == 'true', 'Full destroy IAM readiness is not approved')
                kubernetes.cleanup(region, cluster, execute=execute)
                eks.cleanup(config, os.environ, execute=execute,
                            authorization=approval)
            ec2.cleanup(config, inputs, execute=execute, approval=approval,
                        record_source=delivery['record'], configuration_path=work/'config.json',
                        authorization_action='DESTROY_FULL_STACK' if execute else 'DESTROY_EC2_STACK')
        finally:
            os.chdir(previous)
    print('EC2 cleanup build checks completed')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        run()
    except ec2.CleanupError as error:
        raise SystemExit('Cleanup build stopped: ' + str(error))
    except (ValueError, KeyError, TypeError, OSError, RecursionError, subprocess.SubprocessError):
        raise SystemExit('Cleanup build stopped: invalid configuration or command failure; details withheld')
