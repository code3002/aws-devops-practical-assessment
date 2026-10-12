"""Package committed runtime files; validate an archive before writing any files."""
import argparse
import gzip
import hashlib
import io
from pathlib import Path
import re
import subprocess
import tarfile

FILES = (
    'docker-compose.yml', 'nginx/default.conf', 'app/Dockerfile',
    'app/package.json', 'app/package-lock.json', 'app/app.js',
    'app/server.js', 'app/public/clock.js',
)
MAX_SIZE = 10 * 1024 * 1024


def package(revision, destination):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Require a full immutable commit SHA')
    # Read Git objects, never private/uncommitted working-tree files.
    with open(destination, 'xb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as archive:
                for name in FILES:
                    data = subprocess.check_output(['git', 'show', revision + ':' + name])
                    entry = tarfile.TarInfo(name)
                    entry.size = len(data)
                    entry.mode = 0o644
                    archive.addfile(entry, io.BytesIO(data))
    return hashlib.sha256(Path(destination).read_bytes()).hexdigest()


def extract(source, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('Release directory must not already exist')
    with tarfile.open(source, 'r:gz') as archive:
        members = archive.getmembers()
        names = [entry.name for entry in members]
        if len(names) != len(FILES) or set(names) != set(FILES):
            raise ValueError('Unexpected, missing or duplicate runtime files')
        if any(not entry.isfile() or entry.size < 0 for entry in members):
            raise ValueError('Only regular files are permitted')
        if sum(entry.size for entry in members) > MAX_SIZE:
            raise ValueError('Artifact exceeds size limit')
        # Read and validate everything before extraction; never tar.extractall.
        contents = {entry.name: archive.extractfile(entry).read() for entry in members}
    destination.mkdir(mode=0o750)
    for name, data in contents.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(data)
        target.chmod(0o644)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['package', 'extract'])
    parser.add_argument('source')
    parser.add_argument('destination')
    args = parser.parse_args()
    try:
        if args.operation == 'package':
            print(package(args.source, args.destination))
        else:
            extract(args.source, args.destination)
    except (ValueError, OSError, tarfile.TarError, subprocess.CalledProcessError):
        raise SystemExit('Artifact operation failed; no deployment authorized')
