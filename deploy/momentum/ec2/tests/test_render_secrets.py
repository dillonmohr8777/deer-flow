"""Offline host-loader checks; only synthetic credentials and a fake AWS CLI."""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

EC2 = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "render_secrets", EC2 / "render_secrets.py"
)
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)


class RenderSecretsTests(unittest.TestCase):
    def test_legacy_preserves_order_empty_values_and_settings_without_sdk(self):
        async def unused(*args):
            self.fail("legacy path must not load SDK")

        actual = loader.render_env(
            [["/prod/KEY", "old"], ["/prod/EMPTY", ""]], "TAG=main\n", unused
        )
        self.assertEqual(actual, "KEY='old'\nEMPTY=''\nTAG=main\n")

    def test_enabled_overrides_only_fixed_refs_and_omits_token(self):
        async def resolve(token, refs):
            self.assertEqual(token, "synthetic-token")
            self.assertEqual(
                refs,
                {
                    "BROWSERBASE_API_KEY": "op://ezfukkmm4vt7wqw6vp7l7eli3m/bjil477nt5c433kto6ys3qejw4/credential",
                    "BROWSERBASE_PROJECT_ID": "op://ezfukkmm4vt7wqw6vp7l7eli3m/bjil477nt5c433kto6ys3qejw4/project_id",
                },
            )
            print(token)
            print("provider diagnostic", file=sys.stderr)
            return {
                "BROWSERBASE_API_KEY": "new-key",
                "BROWSERBASE_PROJECT_ID": "new-project",
            }

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            actual = loader.render_env(
                [
                    ["/prod/OP_SERVICE_ACCOUNT_TOKEN", "synthetic-token"],
                    ["/prod/BROWSERBASE_API_KEY", "old-key"],
                    ["/prod/OTHER", "same"],
                ],
                "TAG=main\n",
                resolve,
            )
        self.assertEqual(
            actual,
            "BROWSERBASE_API_KEY='new-key'\nOTHER='same'\nBROWSERBASE_PROJECT_ID='new-project'\nTAG=main\n",
        )
        self.assertEqual(out.getvalue() + err.getvalue(), "")
        self.assertNotIn("synthetic-token", actual)
        self.assertNotIn("OP_SERVICE_ACCOUNT_TOKEN", actual)

    def test_clients_token_is_host_only(self):
        async def unused(*args):
            self.fail("legacy path must not load SDK")

        actual = loader.render_env(
            [["/prod/KEY", "old"], ["/prod/OP_CLIENTS_TOKEN", "ops_synthetic"]], "", unused
        )
        self.assertEqual(actual, "KEY='old'\n")
        with self.assertRaises(ValueError):
            loader.render_env([["/prod/KEY", "old"]], "OP_CLIENTS_TOKEN=x\n", unused)

    def test_invalid_ssm_values_keys_and_shapes_rejected(self):
        for rows in (
            [],
            {},
            [["/prod/A", "line\nbreak"]],
            [["/prod/A", "quote'"]],
            [["/prod/A", "\r"]],
            [["/prod/A", "\0"]],
            [["/prod/A", 12]],
            [["/prod/BAD=KEY", "value"]],
            [["/prod/A"]],
            [["/prod/OP_SERVICE_ACCOUNT_TOKEN", ""]],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                loader.render_env(rows, "")

    def test_invalid_resolved_values_rejected(self):
        for value in ("", " ", "quote'", "line\nbreak", "\r", "\0", None):

            async def resolve(token, refs, value=value):
                return {key: value for key in refs}

            with self.subTest(value=value), self.assertRaises(ValueError):
                loader.render_env(
                    [["/prod/OP_SERVICE_ACCOUNT_TOKEN", "token"]], "", resolve
                )

    def test_settings_cannot_expose_token_or_override_enabled_browserbase(self):
        async def resolve(token, refs):
            return {key: "valid" for key in refs}

        for settings in (
            "OP_SERVICE_ACCOUNT_TOKEN=oops\n",
            " export OP_SERVICE_ACCOUNT_TOKEN =oops\n",
        ):
            with self.assertRaises(ValueError):
                loader.render_env([["/prod/KEY", "value"]], settings)
        with self.assertRaises(ValueError):
            loader.render_env(
                [["/prod/OP_SERVICE_ACCOUNT_TOKEN", "token"]],
                "BROWSERBASE_API_KEY=old\n",
                resolve,
            )

    def test_main_failure_has_no_values_or_partial_stdout(self):
        secret = "synthetic-secret-marker"
        for data in (
            json.dumps([["/prod/FIRST", secret], ["/prod/BAD", "quote'"]]),
            secret,
        ):
            out, err = io.StringIO(), io.StringIO()
            with (
                patch.object(sys, "argv", ["render_secrets", "unused"]),
                patch.object(sys, "stdin", io.StringIO(data)),
                patch.object(Path, "read_text", return_value=""),
                contextlib.redirect_stdout(out),
                contextlib.redirect_stderr(err),
            ):
                self.assertEqual(loader.main(), 1)
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue(), "secret rendering failed\n")

    def test_shell_success_and_provider_failure_preserve_atomic_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            aws = root / "aws"
            aws.write_text(
                '#!/bin/sh\nprintf "%s" "$FAKE_SSM_JSON"\n', encoding="utf-8"
            )
            aws.chmod(0o700)
            (root / "onepassword.py").write_text(
                """
import os
class Client:
    @staticmethod
    async def authenticate(**kwargs):
        if os.environ.get("FAKE_SDK_FAILURE"):
            print(kwargs["auth"])
            raise RuntimeError(kwargs["auth"])
        return Client()
    @property
    def secrets(self):
        return self
    async def resolve(self, ref):
        return "new-key" if ref.endswith("/credential") else "new-project"
""",
                encoding="utf-8",
            )
            settings, output = root / "settings.env", root / "runtime" / ".env"
            settings.write_text("TAG=main\n", encoding="utf-8")
            env = {
                **os.environ,
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "PYTHONPATH": str(root),
                "PYTHONDONTWRITEBYTECODE": "1",
                "MOMOBOT_ENV_FILE": str(output),
                "MOMOBOT_SETTINGS": str(settings),
                "MOMOBOT_SECRETS_PYTHON": sys.executable,
                "FAKE_SSM_JSON": json.dumps([["/prod/KEY", "legacy"]]),
            }
            run = lambda: subprocess.run(
                ["bash", str(EC2 / "secrets.sh")],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_text(), "KEY='legacy'\nTAG=main\n")
            env["FAKE_SSM_JSON"] = json.dumps(
                [["/prod/OP_SERVICE_ACCOUNT_TOKEN", "synthetic-token-marker"]]
            )
            result = run()
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = "BROWSERBASE_API_KEY='new-key'\nBROWSERBASE_PROJECT_ID='new-project'\nTAG=main\n"
            self.assertEqual(output.read_text(), expected)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            env["FAKE_SDK_FAILURE"] = "1"
            result = run()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "secret rendering failed\n")
            self.assertEqual(output.read_text(), expected)
            self.assertEqual(list(output.parent.glob(".env.*")), [])


if __name__ == "__main__":
    unittest.main()
