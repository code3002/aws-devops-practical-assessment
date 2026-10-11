import pathlib
import re
import subprocess
import unittest
import tempfile
import os

SCRIPT = pathlib.Path(__file__).with_name("bootstrap.sh")
TEXT = SCRIPT.read_text()

class BootstrapTests(unittest.TestCase):
    def test_syntax(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_platform_guards_precede_install(self):
        for guard in ["uname -s", "uname -m", "$VERSION_ID == 2023", "$EUID == 0"]:
            self.assertLess(TEXT.index(guard), TEXT.index("dnf install"))

    def test_pinned_verified_download(self):
        self.assertIn("readonly compose_version=2.39.4", TEXT)
        self.assertRegex(TEXT, r"readonly compose_sha256=[a-f0-9]{64}")
        self.assertLess(TEXT.index('"$work_dir/docker-compose" | sha256sum'), TEXT.index('install -o root'))
        self.assertNotIn("--insecure", TEXT)
        self.assertNotRegex(TEXT, r"curl\s+-k")

    def test_service_enable_and_verification(self):
        self.assertIn("systemctl enable --now docker amazon-ssm-agent", TEXT)
        self.assertIn("for service in docker amazon-ssm-agent", TEXT)
        for action in ["is-enabled --quiet", "is-active --quiet"]:
            self.assertIn('systemctl ' + action + ' "$service"', TEXT)
        self.assertIn("rpm -q amazon-ssm-agent", TEXT)
        self.assertIn("docker info", TEXT)

    def test_deployment_prerequisites(self):
        self.assertIn('python3 awscli-2 util-linux', TEXT)
        self.assertIn('for tool in python3 aws flock sha256sum', TEXT)

    def test_existing_directory_rejects_unsafe_owner_permissions_and_links(self):
        function = TEXT[TEXT.index('check_app_directory() {'):TEXT.index('check_app_directory /opt/assessment')]
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            directory = root/'application'; directory.mkdir()
            link = root/'link'; link.symlink_to(directory)
            tools = root/'tools'; tools.mkdir()
            stat = tools/'stat'
            stat.write_text('#!/bin/bash\nprintf "%s\\n" "$FIXTURE_STAT"\n'); stat.chmod(0o700)
            for value, expected in [('0 750', 0), ('0 755', 0), ('1000 750', 1), ('0 777', 1), ('0 775', 1)]:
                result = subprocess.run(['bash', '-c', function + 'check_app_directory "$1"', 'test', str(directory)],
                                        env=os.environ | {'PATH': str(tools)+':'+os.environ['PATH'], 'FIXTURE_STAT': value})
                self.assertEqual(result.returncode, expected, value)
            for path, expected in [(link, 1), (root/'missing', 0)]:
                result = subprocess.run(['bash', '-c', function + 'check_app_directory "$1"', 'test', str(path)])
                self.assertEqual(result.returncode, expected)
        self.assertLess(TEXT.index('check_app_directory /opt/assessment'), TEXT.index('dnf install'))

    def test_preserves_data_and_scope(self):
        self.assertIn('if [[ ! -d /opt/assessment ]]', TEXT)
        self.assertIn('sha256sum --check --status', TEXT)
        self.assertNotIn("docker compose up", TEXT)
        self.assertNotIn("usermod", TEXT)
        self.assertNotIn("PGPASSWORD", TEXT)
        self.assertNotRegex(TEXT, r"rm[^\n]*/opt/assessment")

if __name__ == "__main__":
    unittest.main()
