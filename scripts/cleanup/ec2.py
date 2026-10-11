"""EC2-stack cleanup. Default mode reads and validates; never initializes Terraform."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

STACK = Path(__file__).resolve().parents[2] / 'infrastructure/terraform/ec2'
ROOT = STACK.parents[2]
RESOURCES = set('''aws_vpc.this aws_subnet.this aws_internet_gateway.this
aws_route_table.public aws_route_table.private aws_route.internet aws_route_table_association.this
aws_security_group.alb aws_security_group.ec2 aws_security_group.rds
aws_vpc_security_group_ingress_rule.alb_http aws_vpc_security_group_ingress_rule.ec2_http
aws_vpc_security_group_ingress_rule.ssh aws_vpc_security_group_ingress_rule.postgres
aws_vpc_security_group_egress_rule.alb_http aws_vpc_security_group_egress_rule.ec2_web
aws_vpc_security_group_egress_rule.postgres aws_db_subnet_group.app aws_db_instance.app
aws_instance.app aws_iam_role.app aws_iam_role_policy_attachment.ssm aws_iam_instance_profile.app
aws_lb.app aws_lb_target_group.app aws_lb_listener.http aws_lb_target_group_attachment.app'''.split())
UNTAGGED = {'aws_route.internet', 'aws_route_table_association.this',
            'aws_iam_role_policy_attachment.ssm', 'aws_lb_target_group_attachment.app'}


class CleanupError(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise CleanupError(message)


def command(args):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('TF_', 'AWS_ENDPOINT_URL'))}
    env.update(TF_IN_AUTOMATION='1', AWS_PAGER='')
    result = subprocess.run(args, capture_output=True, text=True, env=env, timeout=3600)
    check(result.returncode == 0, 'Command failed: ' + args[0] + ' ' + args[1])
    return result.stdout


def aws(config, *args):
    return json.loads(command(['aws', '--region', config['region'], '--no-cli-pager', '--output', 'json', *args]))


def source_files(config):
    git = ['git', '-C', str(ROOT)]
    check(command(git + ['rev-parse', 'HEAD']).strip() == config['source_sha'], 'Source revision mismatch')
    prefix = 'infrastructure/terraform/ec2/'
    names = command(git + ['ls-tree', '-r', '--name-only', config['source_sha'], '--', prefix]).splitlines()
    names = {name.removeprefix(prefix) for name in names
             if name.endswith('.tf') or name == prefix + '.terraform.lock.hcl'}
    local = {path.name for path in STACK.glob('*.tf')} | {'.terraform.lock.hcl'}
    check(names == local and '.terraform.lock.hcl' in names, 'Terraform source file inventory mismatch')
    files = {}
    for name in sorted(names):
        content = command(git + ['show', config['source_sha'] + ':' + prefix + name]).encode()
        path = STACK / name
        check(not path.is_symlink() and path.read_bytes() == content, 'Terraform source differs from approved revision')
        files[name] = content
    return files


def configuration(path):
    config = json.loads(Path(path).read_text())
    check(set(config) == {'account', 'region', 'deployment_id', 'bucket', 'key', 'lock_table',
                         'state_lineage', 'never_deployed', 'inputs_file', 'inputs_sha256', 'source_sha'}, 'Unexpected configuration')
    check(re.fullmatch(r'\d{12}', config['account']) and config['region'] == 'ap-south-1', 'Invalid account or region')
    check(re.fullmatch(r'[a-z][a-z0-9-]{2,39}', config['deployment_id']), 'Invalid deployment identifier')
    check(re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', config['bucket']) and config['key'] == 'ec2/terraform.tfstate', 'Invalid backend bucket or EC2 key')
    check(re.fullmatch(r'[A-Za-z0-9_.-]{3,255}', config['lock_table']), 'Invalid lock table')
    check(type(config['never_deployed']) is bool, 'Explicit deployment status required')
    check(config['state_lineage'] is None if config['never_deployed'] else isinstance(config['state_lineage'], str) and bool(config['state_lineage']), 'Retained state lineage required')
    check(re.fullmatch(r'[a-f0-9]{40}', config['source_sha']) and re.fullmatch(r'[a-f0-9]{64}', config['inputs_sha256']), 'Reviewed source and inputs hashes required')
    inputs = Path(config['inputs_file']).read_bytes()
    check(hashlib.sha256(inputs).hexdigest() == config['inputs_sha256'], 'Retained inputs changed')
    values = json.loads(inputs)
    required = {'expected_account_id', 'deployment_id', 'reviewer_ssh_cidr', 'reviewed_ami_id', 'postgres_version'}
    defaults = {'aws_region': 'ap-south-1', 'vpc_cidr': '10.10.0.0/16', 'ssh_key_name': None}
    check(required <= set(values) <= required | set(defaults), 'Unexpected or missing EC2 inputs')
    values = defaults | values
    check(values['aws_region'] == config['region'] and values['expected_account_id'] == config['account'] and values['deployment_id'] == config['deployment_id'], 'Retained input identity mismatch')
    check(values['vpc_cidr'] == '10.10.0.0/16', 'Unexpected VPC range')
    cidr = ipaddress.ip_network(values['reviewer_ssh_cidr'], strict=False)
    check(cidr.version == 4 and 24 <= cidr.prefixlen <= 32, 'Invalid reviewer CIDR')
    check(re.fullmatch(r'ami-[a-f0-9]{17}', values['reviewed_ami_id']) and re.fullmatch(r'[1-9][0-9]\.[0-9]+', values['postgres_version']), 'Invalid retained AMI or PostgreSQL version')
    check(values['ssh_key_name'] is None or isinstance(values['ssh_key_name'], str) and bool(values['ssh_key_name'].strip()), 'Invalid SSH key name')
    return config, inputs


def authorize(config, path):
    check(path is not None, 'Explicit reviewed authorization file required')
    approval = json.loads(Path(path).read_text())
    expected = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    check(set(approval) == {'action', 'configuration_sha256', 'expires_at'} and
          approval['action'] == 'DESTROY_EC2_STACK' and approval['configuration_sha256'] == expected, 'Authorization scope mismatch')
    check(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', approval['expires_at']), 'Invalid authorization expiry')
    check(datetime.fromisoformat(approval['expires_at'].replace('Z', '+00:00')) > datetime.now(timezone.utc), 'Authorization expired')


def state_resources(config, state):
    check(not config['never_deployed'] and state.get('version') == 4 and state.get('lineage') == config['state_lineage'], 'State history mismatch')
    addresses = set()
    for resource in state['resources']:
        if resource['mode'] == 'data':
            continue
        base = resource['type'] + '.' + resource['name']
        check(resource['mode'] == 'managed' and not resource.get('module') and base in RESOURCES, 'Unexpected state resource')
        for instance in resource['instances']:
            index = instance.get('index_key')
            allowed = {'aws_subnet.this': ['public_a', 'public_b', 'database_a', 'database_b'],
                       'aws_route_table_association.this': ['public_a', 'public_b', 'database_a', 'database_b'],
                       'aws_vpc_security_group_egress_rule.ec2_web': ['80', '443']}.get(base, [None])
            check(index in allowed and not instance.get('deposed'), 'Unexpected or deposed resource instance')
            attributes = instance['attributes']
            check(bool(attributes.get('id')), 'Resource identifier missing')
            if base not in UNTAGGED:
                tags = attributes.get('tags_all', {})
                check(tags.get('DeploymentId') == config['deployment_id'] and tags.get('Component') == 'ec2' and tags.get('Project') == 'aws-devops-practical-assessment', 'Resource ownership mismatch')
            address = base + ('[' + json.dumps(index) + ']' if index is not None else '')
            check(address not in addresses, 'Duplicate state instance')
            addresses.add(address)
    ids = {}
    for resource in state['resources']:
        if resource['mode'] == 'managed':
            ids.setdefault(resource['type'] + '.' + resource['name'], set()).update(instance['attributes']['id'] for instance in resource['instances'])
    for resource in state['resources']:
        base = resource['type'] + '.' + resource['name']
        for instance in resource.get('instances', []):
            attributes = instance['attributes']
            if base == 'aws_route.internet':
                check(attributes.get('route_table_id') in ids.get('aws_route_table.public', set()), 'Route parent mismatch')
            elif base == 'aws_route_table_association.this':
                check(attributes.get('route_table_id') in ids.get('aws_route_table.public', set()) | ids.get('aws_route_table.private', set()) and attributes.get('subnet_id') in ids.get('aws_subnet.this', set()), 'Association parent mismatch')
            elif base == 'aws_iam_role_policy_attachment.ssm':
                check(attributes.get('role') == config['deployment_id'] + '-ec2-ssm' and attributes.get('role') in ids.get('aws_iam_role.app', set()) and attributes.get('policy_arn') == 'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore', 'Role attachment mismatch')
            elif base == 'aws_lb_target_group_attachment.app':
                check(attributes.get('target_id') in ids.get('aws_instance.app', set()) and attributes.get('target_group_arn') in ids.get('aws_lb_target_group.app', set()), 'Target attachment mismatch')
    return addresses


def validate_plan(plan, addresses, config, state):
    identifiers = {}
    for resource in state['resources']:
        if resource['mode'] != 'managed': continue
        base = resource['type'] + '.' + resource['name']
        for instance in resource['instances']:
            index = instance.get('index_key')
            address = base + ('[' + json.dumps(index) + ']' if index is not None else '')
            identifiers[address] = instance['attributes']['id']
    changed = set()
    before_by_address = {}
    for resource in plan.get('resource_changes', []):
        actions = resource['change']['actions']
        if actions == ['no-op'] or resource.get('mode') == 'data':
            continue
        check(actions == ['delete'] and resource['address'] in addresses, 'Plan proposes an unexpected change')
        check(resource['change']['before'].get('id') == identifiers[resource['address']], 'Refreshed resource identifier mismatch')
        base = resource['type'] + '.' + resource['name']
        if base not in UNTAGGED:
            tags = resource['change']['before'].get('tags_all', {})
            check(tags.get('DeploymentId') == config['deployment_id'] and tags.get('Component') == 'ec2' and tags.get('Project') == 'aws-devops-practical-assessment', 'Refreshed ownership mismatch')
        changed.add(resource['address'])
        before_by_address[resource['address']] = resource['change']['before']
    check(changed == addresses, 'Plan does not cover the validated stack')
    refreshed = json.loads(json.dumps(state))
    for resource in refreshed['resources']:
        if resource['mode'] != 'managed': continue
        base = resource['type'] + '.' + resource['name']
        for instance in resource['instances']:
            index = instance.get('index_key')
            address = base + ('[' + json.dumps(index) + ']' if index is not None else '')
            instance['attributes'] = before_by_address[address]
    state_resources(config, refreshed)


def check_current_authorization(config, inputs, approval, record_source, configuration_path):
    import record
    import status
    check(record_source is not None and configuration_path is not None, 'Trusted deployment record source required')
    authorize(config, approval)
    deployment_record = record.load_record(record_source, configuration_path)
    check(deployment_record['configuration'] == config, 'Cleanup configuration changed')
    status.load_status(config, record_source, deployment_record)
    # Recheck time after network reads; an authorization may have expired meanwhile.
    record.validate_record(deployment_record, config, inputs)
    authorize(config, approval)


def cleanup(config, inputs, execute=False, approval=None, record_source=None, configuration_path=None):
    check(type(execute) is bool, 'Execution mode must be an explicit boolean')
    if execute:
        authorize(config, approval)
        check(os.environ.get('CODEBUILD_BUILD_ID', '').startswith(config['deployment_id'] + '-destroy:') and os.environ.get('CODEBUILD_RESOLVED_SOURCE_VERSION') == config['source_sha'], 'Execute requires the approved CodeBuild source')
        check_current_authorization(config, inputs, approval, record_source, configuration_path)
    files = source_files(config)
    check(aws(config, 'sts', 'get-caller-identity')['Account'] == config['account'], 'AWS account mismatch')
    owner = ['--expected-bucket-owner', config['account']]
    check(aws(config, 's3api', 'get-bucket-location', '--bucket', config['bucket'], *owner)['LocationConstraint'] == config['region'], 'Backend region mismatch')
    table = aws(config, 'dynamodb', 'describe-table', '--table-name', config['lock_table'])['Table']
    check(table['TableStatus'] == 'ACTIVE' and table['TableArn'] == f"arn:aws:dynamodb:{config['region']}:{config['account']}:table/{config['lock_table']}" and table['KeySchema'] == [{'AttributeName': 'LockID', 'KeyType': 'HASH'}] and {'AttributeName': 'LockID', 'AttributeType': 'S'} in table['AttributeDefinitions'], 'Lock table mismatch')
    listing = aws(config, 's3api', 'list-objects-v2', '--bucket', config['bucket'], '--prefix', config['key'], *owner)
    if not any(item['Key'] == config['key'] for item in listing.get('Contents', [])):
        check(config['never_deployed'], 'Deployed state missing; recovery required')
        print('EC2 stack explicitly undeployed; no cleanup requested')
        return
    with tempfile.TemporaryDirectory(prefix='ec2-cleanup-') as directory:
        work = Path(directory)
        snapshot = work/'state.json'; snapshot.touch(mode=0o600)
        aws(config, 's3api', 'get-object', '--bucket', config['bucket'], '--key', config['key'], *owner, str(snapshot))
        state = json.loads(snapshot.read_text())
        addresses = state_resources(config, state)
        if not addresses:
            print('EC2 state already empty; no cleanup requested')
            return
        print(f'Validated EC2 state: {len(addresses)} managed instances')
        if not execute:
            print('DRY RUN: would initialize isolated S3 backend, lock and review a delete-only plan, then apply it. No Terraform commands executed.')
            return
        check(json.loads(command(['terraform', 'version', '-json']))['terraform_version'] == '1.15.8', 'Pinned Terraform required')
        for name, content in files.items():
            (work/name).write_bytes(content)
        (work/'inputs.tfvars.json').write_bytes(inputs)
        backend = {key: config[key] for key in ['bucket', 'key', 'region']}
        backend.update(encrypt=True, dynamodb_table=config['lock_table'], allowed_account_ids=[config['account']])
        (work/'backend.hcl').write_text(''.join(f'{key} = {json.dumps(value)}\n' for key, value in backend.items()))
        tf = ['terraform', '-chdir=' + str(work)]
        command(tf + ['init', '-reconfigure', '-input=false', '-lockfile=readonly', '-backend-config=backend.hcl'])
        command(tf + ['plan', '-destroy', '-input=false', '-lock=true', '-lock-timeout=60s', '-var-file=inputs.tfvars.json', '-out=destroy.tfplan'])
        validate_plan(json.loads(command(tf + ['show', '-json', 'destroy.tfplan'])), addresses, config, state)
        check_current_authorization(config, inputs, approval, record_source, configuration_path)
        command(tf + ['apply', '-input=false', '-lock=true', '-lock-timeout=60s', 'destroy.tfplan'])
        check(not state_resources(config, json.loads(command(tf + ['state', 'pull']))), 'Managed resources remain after cleanup')
        print('Terraform reports EC2 state empty; independent AWS leftover verification is still required')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('configuration')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--authorization')
    parser.add_argument('--record-source', help='Trusted JSON containing the approved S3 record location, version and hash')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        config, inputs = configuration(args.configuration)
        source = json.loads(Path(args.record_source).read_text()) if args.execute and args.record_source else None
        cleanup(config, inputs, args.execute, args.authorization, source, args.configuration)
    except CleanupError as error:
        raise SystemExit('EC2 cleanup stopped: ' + str(error))
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise SystemExit('EC2 cleanup stopped: validation or command failed; details withheld')
