"""Offline workflow checks with synthetic canonical fixtures.

Set BRAINFORGE_BRIEF_SOURCE to an independently reviewed private brief source.
Only integration
cases that execute its builder/readback skip when it is unavailable. Admission,
hash drift and path-isolation checks still run using inert synthetic programs.
No renderer or private canonical fixture is stored in this repository.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/channels/brainforge_workflow.py"
SPEC = importlib.util.spec_from_file_location("brainforge_workflow_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
workflow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = workflow
SPEC.loader.exec_module(workflow)

SOURCE_SETTING = os.environ.get("BRAINFORGE_BRIEF_SOURCE", "")
PINNED_SOURCE = Path(SOURCE_SETTING)
BRIEF_SOURCE_AVAILABLE = bool(SOURCE_SETTING) and all((PINNED_SOURCE / name).is_file() for name in workflow.BRIEF_MODULES)
INTEGRATION_SOURCE_REASON = "set BRAINFORGE_BRIEF_SOURCE to an independently reviewed private brief source"
THREAD_HASH = hashlib.sha256(b"synthetic test thread").hexdigest()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BrainForgeWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "synthetic-canonical"
        self.source = self.base / "reviewed-brief-source"
        self.source.mkdir()
        for name in workflow.BRIEF_MODULES:
            if BRIEF_SOURCE_AVAILABLE:
                shutil.copyfile(PINNED_SOURCE / name, self.source / name)
            else:
                (self.source / name).write_text("# Inert synthetic program for admission-only checks.\n", encoding="utf-8")
        (self.root / "registry").mkdir(parents=True)
        (self.root / "queue").mkdir()
        self.registry = {
            "clients": [
                {"id": "example", "status": "active", "contacts": "CONTACT_SENTINEL"},
                {"id": "other", "status": "active"},
            ]
        }
        self.queue = {
            "revision": 7,
            "updatedAt": "2026-10-02T00:00:00+00:00",
            "workItems": [
                {
                    "id": "one",
                    "clientId": "example",
                    "status": "blocked",
                    "title": "PRIVATE_CLIENT_PROSE",
                    "body": "BODY_SENTINEL",
                },
                {"id": "two", "clientId": "example", "status": "done"},
                {"id": "three", "clientId": "other", "status": "deferred"},
                {"id": "four", "clientId": "absent", "status": "blocked"},
            ],
        }
        self.save()
        self.config = {
            "brief_source": str(self.source),
            "canonical_root": str(self.root),
            "artifact_root": str(self.base / "private-output"),
            "brief_source_hashes": {name: digest(self.source / name) for name in workflow.BRIEF_MODULES},
            "source_hashes": self.source_hashes(),
        }

    def save(self) -> None:
        (self.root / "registry/clients.json").write_text(json.dumps(self.registry), encoding="utf-8")
        (self.root / "queue/work-items.json").write_text(json.dumps(self.queue), encoding="utf-8")

    def source_hashes(self) -> dict[str, str]:
        return {name: digest(self.root / name) for name in workflow.SOURCE_FILES}

    def run_workflow(self, client: str = "__owner__"):
        return workflow.BrainForgeBriefWorkflow(self.config).run(job_key="synthetic test job", client_id=client, thread_sha256=THREAD_HASH)

    @unittest.skipUnless(BRIEF_SOURCE_AVAILABLE, INTEGRATION_SOURCE_REASON)
    def test_owner_receipt_real_readback_private_output_and_unchanged_inputs(self) -> None:
        before = self.source_hashes()
        result = self.run_workflow()
        self.assertEqual(result.counts["workItems"], 4)
        self.assertEqual(result.counts["nonterminal"], 3)
        self.assertEqual(result.counts["unresolvedRoutes"], 1)
        self.assertEqual(result.queue_revision, 7)
        receipt_path = Path(result.receipt_path)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(digest(receipt_path), result.receipt_sha256)
        self.assertTrue(receipt["readbackVerified"])
        self.assertTrue(receipt["inputsUnchanged"])
        self.assertEqual(receipt["threadSha256"], THREAD_HASH)
        for sentinel in ("PRIVATE_CLIENT_PROSE", "CONTACT_SENTINEL", "BODY_SENTINEL"):
            self.assertNotIn(sentinel, result.text)
            self.assertNotIn(sentinel, receipt_path.read_text(encoding="utf-8"))
        for directory in (receipt_path.parent, receipt_path.parent.parent):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for artifact in receipt_path.parent.iterdir():
            self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)
        self.assertEqual(before, self.source_hashes())

    @unittest.skipUnless(BRIEF_SOURCE_AVAILABLE, INTEGRATION_SOURCE_REASON)
    def test_client_counts_do_not_include_other_routes(self) -> None:
        result = self.run_workflow("example")
        self.assertEqual(
            result.counts,
            {"workItems": 2, "statuses": {"blocked": 1, "done": 1}, "nonterminal": 1, "unresolvedRoutes": 0},
        )
        self.assertNotIn("deferred", result.text)

    def test_unknown_route_rejected_without_canonical_mutation(self) -> None:
        before = self.source_hashes()
        with self.assertRaisesRegex(ValueError, "route"):
            self.run_workflow("not-recorded")
        self.assertEqual(before, self.source_hashes())

    def test_unknown_route_cannot_launch_builder(self) -> None:
        runner = workflow.BrainForgeBriefWorkflow(self.config)
        with patch.object(workflow.subprocess, "run", side_effect=AssertionError("invalid route launched builder")):
            with self.assertRaisesRegex(ValueError, "route"):
                runner.run(job_key="bad route", client_id="not-recorded", thread_sha256=THREAD_HASH)

    def test_source_drift_refuses_execution_before_output(self) -> None:
        runner = workflow.BrainForgeBriefWorkflow(self.config)
        self.queue["revision"] = 8
        self.save()
        with self.assertRaisesRegex(ValueError, "source drift"):
            runner.run(job_key="changed queue", client_id="example", thread_sha256=THREAD_HASH)
        self.assertFalse(Path(self.config["artifact_root"]).exists())

    def test_registry_drift_refuses_execution(self) -> None:
        runner = workflow.BrainForgeBriefWorkflow(self.config)
        self.registry["clients"][0]["status"] = "inactive"
        self.save()
        with self.assertRaisesRegex(ValueError, "source drift"):
            runner.run(job_key="changed registry", client_id="example", thread_sha256=THREAD_HASH)

    def test_reviewed_program_drift_refuses_execution(self) -> None:
        runner = workflow.BrainForgeBriefWorkflow(self.config)
        with (self.source / "daily_brief.py").open("a", encoding="utf-8") as stream:
            stream.write("\n# Changed program\n")
        with self.assertRaisesRegex(ValueError, "source drift"):
            runner.run(job_key="changed implementation", client_id="example", thread_sha256=THREAD_HASH)

    def test_output_inside_either_source_tree_rejected(self) -> None:
        for source in (self.root, self.source):
            with self.subTest(source=source):
                config = dict(self.config, artifact_root=str(source / "output"))
                with self.assertRaisesRegex(ValueError, "outside source trees"):
                    workflow.BrainForgeBriefWorkflow(config)

    def test_output_symlink_ancestor_rejected(self) -> None:
        target = self.base / "shared-target"
        target.mkdir()
        link = self.base / "linked-output"
        link.symlink_to(target, target_is_directory=True)
        config = dict(self.config, artifact_root=str(link / "private"))
        with self.assertRaisesRegex(ValueError, "symlink|unsafe"):
            workflow.BrainForgeBriefWorkflow(config)
        self.assertFalse((target / "private").exists())

    def test_incomplete_reviewed_hash_pins_refused(self) -> None:
        config = dict(self.config)
        config["brief_source_hashes"] = {"daily_brief.py": self.config["brief_source_hashes"]["daily_brief.py"]}
        with self.assertRaisesRegex(ValueError, "complete source hash pins"):
            workflow.BrainForgeBriefWorkflow(config)

    def test_invalid_thread_hash_refused_before_output(self) -> None:
        runner = workflow.BrainForgeBriefWorkflow(self.config)
        with self.assertRaisesRegex(ValueError, "thread hash"):
            runner.run(job_key="invalid context", client_id="example", thread_sha256="unverified")
        self.assertFalse(Path(self.config["artifact_root"]).exists())

    @unittest.skipUnless(BRIEF_SOURCE_AVAILABLE, INTEGRATION_SOURCE_REASON)
    def test_unified_project_is_bound_to_receipt_and_independent_readback(self) -> None:
        from app.channels.brainforge_cli import verify

        control = self.root / "CONTROL.md"
        control.write_text("Synthetic canonical owner rules", encoding="utf-8")
        catalog = self.base / "catalog.json"
        catalog.write_text(json.dumps({"workflows": []}), encoding="utf-8")
        self.config["project"] = {
            "control": {"path": str(control), "sha256": digest(control)},
            "catalog": {"path": str(catalog), "sha256": digest(catalog)},
            "inputs": {},
            "research": None,
            "collector": {"total_budget_usd": 16, "ledger": None},
        }
        result = self.run_workflow()
        self.assertEqual(result.counts["projectRequestsPrepared"], 0)
        self.assertLessEqual(len(result.text.splitlines()), 6)
        receipt = json.loads(Path(result.receipt_path).read_text(encoding="utf-8"))
        project_path = Path(receipt["project"]["path"])
        self.assertEqual(digest(project_path), receipt["project"]["sha256"])
        self.assertEqual(stat.S_IMODE(project_path.stat().st_mode), 0o600)
        self.assertTrue(verify(result.receipt_path, result.receipt_sha256, self.config)["projectVerified"])
        project_path.write_text('{"tampered": true}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source drift"):
            verify(result.receipt_path, result.receipt_sha256, self.config)

    def test_project_control_must_be_from_same_canonical_tree(self) -> None:
        self.config["project"] = {"control": {"path": str(self.base / "different/CONTROL.md"), "sha256": "a" * 64}}
        with self.assertRaisesRegex(ValueError, "same canonical"):
            workflow.BrainForgeBriefWorkflow(self.config)

    @unittest.skipUnless(BRIEF_SOURCE_AVAILABLE, INTEGRATION_SOURCE_REASON)
    def test_duplicate_and_missing_work_ids_rejected_by_real_builder(self) -> None:
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    self.queue["workItems"] = [{"clientId": "example", "status": "blocked"}]
                else:
                    self.queue["workItems"] = [{"id": "duplicate", "clientId": "example", "status": "blocked"}] * 2
                self.save()
                self.config["source_hashes"] = self.source_hashes()
                with self.assertRaisesRegex(ValueError, "brief build failed"):
                    self.run_workflow()

    @unittest.skipUnless(BRIEF_SOURCE_AVAILABLE, INTEGRATION_SOURCE_REASON)
    def test_tampered_brief_and_snapshot_cannot_complete(self) -> None:
        original_run = workflow.subprocess.run
        for target in ("brief", "snapshot"):
            with self.subTest(target=target):

                def mutate_then_read(args, **kwargs):
                    if "read" in args:
                        manifest_path = Path(args[args.index("--manifest") + 1])
                        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                        Path(manifest[target]["path"]).write_text("tampered artifact", encoding="utf-8")
                    return original_run(args, **kwargs)

                with patch.object(workflow.subprocess, "run", side_effect=mutate_then_read):
                    with self.assertRaisesRegex(ValueError, "protected brief readback failed"):
                        self.run_workflow()


if __name__ == "__main__":
    unittest.main()
