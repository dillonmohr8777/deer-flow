"""Run the deployed health script with isolated command doubles, without Docker or network."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HEALTH = Path(__file__).resolve().parents[2] / "deploy/momentum/lightsail/health.sh"


@unittest.skipUnless(shutil.which("bash"), "shell health check requires Bash")
class LightsailHealthTests(unittest.TestCase):
    def run_health(self, **overrides):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commands = root / "bin"
            commands.mkdir()
            scripts = {
                "docker": 'exit "${TEST_DOCKER_EXIT:-0}"',
                "curl": """case "${*: -1}" in
  https://momo.invalid/)
    [[ " $* " == *" --location "* ]] || { printf 307; exit; }
    printf '%s' "$TEST_UI_CODE" ;;
  *health/ready) printf '%s' "$TEST_READY_CODE" ;;
  *) printf 200 ;;
esac""",
                "df": """printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\n'
printf '/dev/test 80000000 10000000 %s 13%% /\n' "$TEST_DISK_KIB"
exit "${TEST_DF_EXIT:-0}"
""",
                "stat": 'printf "%s\\n" "$TEST_BACKUP_TIME"',
            }
            for name, body in scripts.items():
                executable = commands / name
                executable.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
                executable.chmod(0o755)
            (root / "last-backup-ok").touch()
            (root / ".env").write_text("MOMOBOT_DOMAIN=momo.invalid\n", encoding="utf-8")
            env = dict(os.environ)
            env.update(
                PATH=f"{commands}{os.pathsep}{env['PATH']}",
                MOMOBOT_DEPLOY_DIR=str(root),
                MOMOBOT_ENV_FILE=str(root / ".env"),
                MOMOBOT_HEALTH_LOG=str(root / "health.jsonl"),
                TEST_DISK_KIB=str(20 * 1024 * 1024),
                TEST_BACKUP_TIME=str(int(time.time())),
                TEST_UI_CODE="200",
                TEST_READY_CODE="200",
            )
            env.update(overrides)
            result = subprocess.run(["bash", str(HEALTH)], env=env, capture_output=True, text=True, check=False)
            self.assertTrue(result.stdout.strip(), result.stderr)
            record = json.loads(result.stdout.splitlines()[-1])
            self.assertEqual(json.loads((root / "health.jsonl").read_text().splitlines()[-1]), record)
            return result.returncode, record

    def test_healthy_host(self):
        code, record = self.run_health()
        self.assertEqual(code, 0)
        self.assertTrue(record["ok"])
        self.assertEqual(record["diskAvailableMiB"], 20480)
        self.assertEqual(record["publicUi"], "200")

    def test_insufficient_space_fails_even_when_app_and_backup_work(self):
        code, record = self.run_health(TEST_DISK_KIB=str(9 * 1024 * 1024))
        self.assertEqual(code, 1)
        self.assertFalse(record["ok"])
        self.assertEqual(record["diskAvailableMiB"], 9216)

    def test_ten_gib_boundary_passes(self):
        code, record = self.run_health(TEST_DISK_KIB=str(10 * 1024 * 1024))
        self.assertEqual(code, 0)
        self.assertTrue(record["ok"])

    def test_unknown_disk_fails(self):
        code, record = self.run_health(TEST_DISK_KIB="unavailable")
        self.assertEqual(code, 1)
        self.assertFalse(record["ok"])
        self.assertIsNone(record["diskAvailableMiB"])

    def test_failed_df_does_not_accept_partial_output(self):
        code, record = self.run_health(TEST_DF_EXIT="1")
        self.assertEqual(code, 1)
        self.assertFalse(record["ok"])
        self.assertIsNone(record["diskAvailableMiB"])

    def test_unavailable_frontend_fails(self):
        code, record = self.run_health(TEST_UI_CODE="503")
        self.assertEqual(code, 1)
        self.assertFalse(record["ok"])
        self.assertEqual(record["publicUi"], "503")

    def test_stale_backup_still_fails(self):
        code, record = self.run_health(TEST_BACKUP_TIME=str(int(time.time()) - 28 * 3600))
        self.assertEqual(code, 1)
        self.assertFalse(record["ok"])

    def test_unready_gateway_still_fails(self):
        code, record = self.run_health(TEST_READY_CODE="503")
        self.assertEqual(code, 1)
        self.assertFalse(record["ok"])


if __name__ == "__main__":
    unittest.main()
