import pathlib
import re
import subprocess
import unittest

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

    def test_preserves_data_and_scope(self):
        self.assertIn('if [[ ! -d /opt/assessment ]]', TEXT)
        self.assertIn('sha256sum --check --status', TEXT)
        self.assertNotIn("docker compose up", TEXT)
        self.assertNotIn("usermod", TEXT)
        self.assertNotIn("PGPASSWORD", TEXT)
        self.assertNotRegex(TEXT, r"rm[^\n]*/opt/assessment")

if __name__ == "__main__":
    unittest.main()
