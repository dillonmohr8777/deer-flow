"""Offline candidate configuration checks; fixtures contain no real identities."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from app.channels import brainforge_cli
from app.channels import brainforge_setup as setup


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "brief"
        self.canonical = self.base / "canonical"
        self.storage = self.base / "private"
        self.output = self.storage / "candidate.yaml"
        self.source.mkdir()
        for name in setup.BRIEF_MODULES:
            (self.source / name).write_text("raise AssertionError('BUILDER_MUST_NOT_EXECUTE')\n")
        (self.canonical / "registry").mkdir(parents=True)
        (self.canonical / "queue").mkdir()
        (self.canonical / "registry/clients.json").write_text(json.dumps({"clients": [{"id": "example", "status": "active"}, {"id": "inactive", "status": "inactive"}]}))
        (self.canonical / "queue/work-items.json").write_text(json.dumps({"revision": 1, "workItems": [], "private": "PRIVATE_SOURCE_SENTINEL"}))
        self.bindings = {"team_id": "T123", "bot_user_id": "U999", "allowed_users": ["U123"], "channel_clients": {"C123": "example"}, "owner_user_id": "U123", "connection_owner_id": "synthetic-owner"}
        self.binding_file = self.base / "bindings.json"
        self.binding_file.write_text(json.dumps(self.bindings))

    def prepare(self, **changes):
        return setup.prepare(brief_source=str(self.source), canonical_root=str(self.canonical), storage_root=str(self.storage), out=str(self.output), **{"bindings": str(self.binding_file), **changes})

    def document(self):
        return yaml.safe_load(self.output.read_text())

    def save(self, document):
        self.output.write_text(yaml.safe_dump(document))

    def cli(self, *arguments):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = setup.main(list(arguments))
        return code, stream.getvalue()

    def test_prepare_and_check_are_offline_private_disabled_and_source_unchanged(self):
        before = {str(path): path.read_bytes() for path in self.canonical.rglob("*.json")}
        with patch("subprocess.run", side_effect=AssertionError("No subprocess permitted")), patch("socket.socket", side_effect=AssertionError("No network permitted")):
            report = self.prepare()
            checked = setup.check(str(self.output))
        config = self.document()["channels"]["slack"]["brain_forge"]
        self.assertTrue(report["prepared"])
        self.assertTrue(checked["local_configuration_ready"])
        self.assertEqual(checked["live_readiness"], "unverified")
        self.assertFalse(config["enabled"])
        self.assertTrue(config["require_connection"])
        self.assertEqual(config["source_pin_status"], "candidate_unreviewed")
        self.assertFalse(Path(config["ledger_path"]).exists())
        self.assertFalse(Path(config["workflow"]["artifact_root"]).exists())
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.canonical.rglob("*.json")})
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.storage.stat().st_mode), 0o700)
        self.assertNotIn("PRIVATE_SOURCE_SENTINEL", self.output.read_text())

    def test_missing_bindings_prepare_template_and_check_exits_nonzero(self):
        report = self.prepare(bindings=None)
        self.assertFalse(report["local_configuration_ready"])
        self.assertEqual(set(report["missing_binding_fields"]), setup.BINDINGS)
        code, raw = self.cli("check", "--fragment", str(self.output))
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(raw)["local_configuration_ready"])

    def test_source_drift_fails_check_without_repinning(self):
        self.prepare()
        original = self.output.read_bytes()
        (self.canonical / "queue/work-items.json").write_text('{"revision":2,"workItems":[]}')
        code, raw = self.cli("check", "--fragment", str(self.output))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(raw)["reason"], "source_pins_invalid_or_drifted")
        self.assertEqual(self.output.read_bytes(), original)

    def test_existing_output_is_never_overwritten(self):
        self.prepare()
        original = self.output.read_bytes()
        with self.assertRaisesRegex(setup.SetupError, "output_already_exists"):
            self.prepare()
        self.assertEqual(self.output.read_bytes(), original)

    def test_new_candidates_use_distinct_artifact_directories(self):
        self.prepare()
        first = self.document()["channels"]["slack"]["brain_forge"]["workflow"]["artifact_root"]
        self.output = self.storage / "second.yaml"
        self.prepare()
        self.assertNotEqual(first, self.document()["channels"]["slack"]["brain_forge"]["workflow"]["artifact_root"])

    def test_output_and_storage_cannot_overlap_either_source_tree(self):
        for root in (self.source, self.canonical):
            with self.subTest(root=root), self.assertRaises(setup.SetupError):
                setup.prepare(brief_source=str(self.source), canonical_root=str(self.canonical), storage_root=str(root / "private"), out=str(self.output))
            with self.subTest(root=root), self.assertRaises(setup.SetupError):
                setup.prepare(brief_source=str(self.source), canonical_root=str(self.canonical), storage_root=str(self.storage), out=str(root / "candidate.yaml"))
        self.assertFalse(self.storage.exists())

    def test_symlink_ancestor_source_output_and_binding_rejected(self):
        link = self.base / "linked"
        link.symlink_to(self.base, target_is_directory=True)
        for changes in ({"storage_root": str(link / "private")}, {"brief_source": str(link / "brief")}, {"bindings": str(link / "bindings.json")}):
            options = {"brief_source": str(self.source), "canonical_root": str(self.canonical), "storage_root": str(self.storage), "out": str(self.output), **changes}
            with self.subTest(changes=changes), self.assertRaisesRegex(setup.SetupError, "symlink"):
                setup.prepare(**options)
        self.assertFalse(self.storage.exists())

    def test_registry_directory_symlink_rejected_before_pinning(self):
        (self.canonical / "registry").rename(self.base / "external-registry")
        (self.canonical / "registry").symlink_to(self.base / "external-registry", target_is_directory=True)
        with self.assertRaisesRegex(setup.SetupError, "symlink"):
            self.prepare()

    def test_duplicate_binding_json_and_candidate_yaml_keys_rejected(self):
        self.binding_file.write_text('{"team_id":"T123","team_id":"T999"}')
        with self.assertRaisesRegex(setup.SetupError, "duplicate"):
            self.prepare()
        self.binding_file.write_text(json.dumps(self.bindings))
        self.prepare()
        self.output.write_text(self.output.read_text() + "channels: {}\n")
        code, raw = self.cli("check", "--fragment", str(self.output))
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(raw)["reason"], "duplicate_or_invalid_key")

    def test_duplicate_registry_keys_are_rejected_before_output(self):
        (self.canonical / "registry/clients.json").write_text('{"clients":[],"clients":[]}')
        with self.assertRaisesRegex(setup.SetupError, "duplicate"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_malformed_or_credential_binding_is_rejected_without_echo(self):
        for raw in [{"bot_token": "PRIVATE_CREDENTIAL_SENTINEL"}, {"allowed_users": "U123"}, {"channel_clients": []}, {"connection_owner_id": "xoxb-PRIVATE_CREDENTIAL_SENTINEL"}]:
            self.binding_file.write_text(json.dumps(raw))
            code, output = self.cli("prepare", "--brief-source", str(self.source), "--canonical-root", str(self.canonical), "--storage-root", str(self.storage), "--out", str(self.output), "--bindings", str(self.binding_file))
            self.assertEqual(code, 2)
            self.assertNotIn("PRIVATE_CREDENTIAL_SENTINEL", output)
            self.assertNotIn(str(self.base), output)
        self.assertFalse(self.output.exists())

    def test_inactive_unknown_and_wrong_owner_routes_fail_local_readiness(self):
        for route, owner in [("inactive", "U123"), ("missing", "U123"), ("__owner__", "UOTHER")]:
            self.binding_file.write_text(json.dumps({**self.bindings, "channel_clients": {"C123": route}, "owner_user_id": owner}))
            self.assertFalse(self.prepare()["local_configuration_ready"])
            self.output.unlink()

    def test_ambiguous_registry_ids_fail(self):
        (self.canonical / "registry/clients.json").write_text(json.dumps({"clients": [{"id": "example", "status": "active"}] * 2}))
        with self.assertRaisesRegex(setup.SetupError, "ambiguous_registry"):
            self.prepare()

    def test_enabled_or_credential_containing_fragment_is_rejected(self):
        self.prepare()
        for key, value in [("enabled", True), ("require_connection", False), ("bot_token", "PRIVATE_SECRET")]:
            document = self.document()
            config = document["channels"]["slack"]["brain_forge"]
            original = dict(config)
            config[key] = value
            self.save(document)
            code, raw = self.cli("check", "--fragment", str(self.output))
            self.assertEqual(code, 2)
            self.assertNotIn("PRIVATE_SECRET", raw)
            document["channels"]["slack"]["brain_forge"] = original
            self.save(document)

    def test_ledger_inside_source_or_artifact_and_fragment_overlap_rejected(self):
        self.prepare()
        document = self.document()
        config = document["channels"]["slack"]["brain_forge"]
        for target in [self.canonical / "receipts.sqlite", Path(config["workflow"]["artifact_root"]) / "receipts.sqlite", self.output]:
            config["ledger_path"] = str(target)
            self.save(document)
            with self.assertRaises(setup.SetupError):
                setup.check(str(self.output))

    def test_existing_public_storage_is_rejected_without_chmod(self):
        if os.name != "posix":
            self.skipTest("POSIX permission check")
        self.storage.mkdir(mode=0o755)
        self.storage.chmod(0o755)
        with self.assertRaisesRegex(setup.SetupError, "private_path_required"):
            self.prepare()
        self.assertEqual(stat.S_IMODE(self.storage.stat().st_mode), 0o755)

    def test_environment_checks_only_report_presence_never_values(self):
        self.prepare()
        with patch.dict(os.environ, {name: "PRIVATE_ENV_SENTINEL" for name in setup.ENV_REFERENCES}):
            code, raw = self.cli("check", "--fragment", str(self.output))
        self.assertEqual(code, 0)
        self.assertTrue(all(json.loads(raw)["environment_presence"].values()))
        self.assertNotIn("PRIVATE_ENV_SENTINEL", raw)
        self.assertIn("encrypted_connection_token", json.loads(raw)["unverified"])

    def test_existing_cli_dispatches_check_without_changing_old_preflight(self):
        self.prepare()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as exit_context:
            brainforge_cli.main(["check", "--fragment", str(self.output)])
        self.assertEqual(exit_context.exception.code, 0)
        config = self.document()["channels"]["slack"]["brain_forge"]["workflow"]
        old_config = self.base / "workflow.json"
        old_config.write_text(json.dumps(config))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            brainforge_cli.main(["preflight", "--config", str(old_config)])
        self.assertEqual(json.loads(output.getvalue())["status"], "local_source_pins_valid")

    def test_optional_project_is_validated_without_stripping_or_execution(self):
        self.prepare()
        document = self.document()
        config = document["channels"]["slack"]["brain_forge"]["workflow"]
        control = self.canonical / "CONTROL.md"
        control.write_text("# Synthetic control\n")
        catalog = self.base / "catalog.json"
        catalog.write_text('{"workflows":[]}')
        config["project"] = {
            "control": {"path": str(control), "sha256": hashlib.sha256(control.read_bytes()).hexdigest()},
            "catalog": {"path": str(catalog), "sha256": hashlib.sha256(catalog.read_bytes()).hexdigest()},
            "collector": {"total_budget_usd": 16},
        }
        self.save(document)
        with patch("subprocess.run", side_effect=AssertionError("No builder")):
            self.assertTrue(setup.check(str(self.output))["local_configuration_ready"])
        self.assertEqual(self.document()["channels"]["slack"]["brain_forge"]["workflow"]["project"], config["project"])


if __name__ == "__main__":
    unittest.main()
