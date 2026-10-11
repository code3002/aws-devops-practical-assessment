import hashlib
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import artifact

HERE = Path(__file__).parent

class DeliveryTests(unittest.TestCase):
    def archive(self, path, extra=None, link=False):
        with tarfile.open(path, 'w:gz') as out:
            for name in artifact.FILES:
                entry = tarfile.TarInfo(name)
                data = b'runtime-file'
                entry.size = len(data)
                if link and name == artifact.FILES[0]:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = '/etc/passwd'
                out.addfile(entry, io.BytesIO(data))
            if extra:
                entry = tarfile.TarInfo(extra)
                out.addfile(entry, io.BytesIO(b''))

    def test_committed_package_roundtrip_and_determinism(self):
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip()
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            one = artifact.package(sha, d/'one.tar.gz')
            self.assertEqual(one, artifact.package(sha, d/'two.tar.gz'))
            artifact.extract(d/'one.tar.gz', d/'release')
            files = {str(p.relative_to(d/'release')) for p in (d/'release').rglob('*') if p.is_file()}
            self.assertEqual(files, set(artifact.FILES))
            self.assertFalse(any('.env' in f for f in files))

    def test_reject_traversal_absolute_unexpected_and_duplicate(self):
        for extra in ['../escape', '/etc/passwd', '.env', artifact.FILES[0]]:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as d:
                d = Path(d)
                self.archive(d/'a.tar.gz', extra=extra)
                with self.assertRaises(ValueError): artifact.extract(d/'a.tar.gz', d/'release')
                self.assertFalse((d/'release').exists())

    def test_reject_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d); self.archive(d/'a.tar.gz', link=True)
            with self.assertRaises(ValueError): artifact.extract(d/'a.tar.gz', d/'release')
            self.assertFalse((d/'release').exists())

    def test_reject_hardlink_and_oversized_archive(self):
        for kind in ["hardlink", "oversized"]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as d:
                path = Path(d)/"a.tar.gz"
                with tarfile.open(path, "w:gz") as out:
                    for name in artifact.FILES:
                        entry = tarfile.TarInfo(name)
                        if name == artifact.FILES[0]:
                            if kind == "hardlink":
                                entry.type = tarfile.LNKTYPE
                                entry.linkname = "/etc/passwd"
                            else:
                                entry.size = artifact.MAX_SIZE + 1
                        out.addfile(entry, io.BytesIO(b"\0" * entry.size))
                with self.assertRaises(ValueError):
                    artifact.extract(path, Path(d)/"release")
                self.assertFalse((Path(d)/"release").exists())

    def test_reject_existing_destination_and_mutable_revision(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): artifact.extract('unused', d)
            with self.assertRaises(ValueError): artifact.package('main', Path(d)/'a.tar.gz')

    def test_shell_syntax(self):
        subprocess.run(['bash', '-n', str(HERE/'deploy.sh')], check=True)

    def test_integrity_before_execution_and_private_runtime(self):
        text = (HERE/'deploy.sh').read_text()
        self.assertLess(text.index('sha256sum --check'), text.index('artifact.py" extract'))
        self.assertLess(text.index('artifact.py" extract'), text.index("compose \"$release\" config"))
        self.assertIn('--version-id "$version"', text)
        self.assertIn('0:600', text)
        self.assertNotIn('set -x', text)
        self.assertIn('flock -n', text)

    def test_rollback_and_health_gate(self):
        text = (HERE/'deploy.sh').read_text()
        self.assertIn('compose "$previous" up -d --no-build', text)
        self.assertIn('healthy "$previous"', text)
        self.assertIn('com.docker.compose.project.working_dir', text)
        self.assertIn('assessment-app:%s', text)
        self.assertIn('docker image inspect', text)
        self.assertIn('diff -qr --no-dereference', text)
        self.assertLess(text.index('http://127.0.0.1/health'), text.index('mv -Tf'))
        self.assertIn('No previous release; candidate containers stopped', text)

if __name__ == '__main__': unittest.main()
