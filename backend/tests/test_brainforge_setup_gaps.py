"""Offline candidate configuration checks; fixtures contain no real identities."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from app.channels import brainforge_setup as setup


class SetupGapsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
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
        args = {"brief_source": str(self.source), "canonical_root": str(self.canonical), "storage_root": str(self.storage), "out": str(self.output), "bindings": str(self.binding_file), **changes}
        return setup.prepare(**args)

    def document(self):
        return yaml.safe_load(self.output.read_text())

    def save(self, document):
        self.output.write_text(yaml.safe_dump(document))

    def cli(self, *arguments):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = setup.main(list(arguments))
        return code, stream.getvalue()

    def test_yaml_alias_not_allowed(self):
        self.prepare()
        self.output.write_text("a: &x 1\nb: *x\n")
        with self.assertRaisesRegex(setup.SetupError, "yaml_alias_not_allowed"):
            setup.check(str(self.output))

    def test_invalid_path_dot_dot(self):
        with self.assertRaisesRegex(setup.SetupError, "invalid_path"):
            setup.check(str(self.base / ".." / "evil"))

    def test_symlink_path_parent(self):
        real = self.base / "real"
        real.mkdir()
        link = self.base / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaisesRegex(setup.SetupError, "symlink_path"):
            setup.check(str(link / "candidate.yaml"))

    def test_credential_shaped_binding_rejected(self):
        bad = dict(self.bindings)
        bad["team_id"] = "xoxb-" + "synthetic-test-value"
        self.binding_file.write_text(json.dumps(bad))
        with self.assertRaisesRegex(setup.SetupError, "credential_shaped_binding_rejected"):
            self.prepare()

    def test_overlapping_source_or_storage_paths(self):
        with self.assertRaisesRegex(setup.SetupError, "overlapping_source_or_storage_paths"):
            self.prepare(storage_root=str(self.source))

    def test_invalid_registry(self):
        (self.canonical / "registry/clients.json").write_text(json.dumps({"clients": "bad"}))
        with self.assertRaisesRegex(setup.SetupError, "invalid_registry"):
            self.prepare()

    def test_local_configuration_incomplete_cli_empty_bindings(self):
        code, text = self.cli("prepare", f"--brief-source={self.source}", f"--canonical-root={self.canonical}", f"--storage-root={self.storage}", f"--out={self.output}")
        self.assertEqual(code, 1)
        self.assertIn("local_configuration_incomplete", text)

    def test_disabled_candidate_fragment_required_enabled_true(self):
        self.prepare()
        doc = self.document()
        doc["channels"]["slack"]["brain_forge"]["enabled"] = True
        self.save(doc)
        with self.assertRaisesRegex(setup.SetupError, "disabled_candidate_fragment_required"):
            setup.check(str(self.output))
