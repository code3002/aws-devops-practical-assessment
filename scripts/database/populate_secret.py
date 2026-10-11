"""Populate only an empty application secret; dry-run unless --execute is explicit."""
import argparse
import json
import re
import secrets
import subprocess


def request(*args, payload=None):
    result = subprocess.run(['aws', '--region', 'ap-south-1', '--no-cli-pager', '--output', 'json', *args],
                            input=payload, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('AWS operation failed; output withheld')
    return json.loads(result.stdout)


def populate(account, arn, execute=False):
    if not re.fullmatch(r'\d{12}', account) or not re.fullmatch(r'arn:aws:secretsmanager:ap-south-1:' + account + r':secret:[A-Za-z0-9/_+=.@-]+', arn):
        raise ValueError('Invalid account or application secret')
    if request('sts', 'get-caller-identity')['Account'] != account:
        raise ValueError('Account mismatch')
    metadata = request('secretsmanager', 'describe-secret', '--secret-id', arn)
    if metadata['ARN'] != arn or metadata.get('DeletedDate'):
        raise ValueError('Secret identity or lifecycle mismatch')
    if any('AWSCURRENT' in stages for stages in metadata.get('VersionIdsToStages', {}).values()):
        print('Application secret already populated; rotation not attempted')
        return
    if metadata.get('VersionIdsToStages'):
        raise ValueError('Existing versions without AWSCURRENT require operator review')
    if not execute:
        print('DRY RUN: would generate and populate application credentials; no AWS writes')
        return
    payload = json.dumps({'username': 'assessment_app', 'password': secrets.token_urlsafe(32)})
    # The AWS CLI reads the payload from stdin, never an argument or temporary file.
    request('secretsmanager', 'put-secret-value', '--secret-id', arn,
            '--secret-string', 'file:///dev/stdin', payload=payload)
    print('Application secret populated; value withheld')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument('account')
    parser.add_argument('secret_arn')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        populate(args.account, args.secret_arn, args.execute)
    except Exception:
        raise SystemExit('Application secret population failed; details withheld')
