"""Strict startup binding tests; synthetic data only."""

from __future__ import annotations

import hashlib
import json
import os
import stat

import pytest

from app.gateway.jevbox_preparation_binding import (
    MAX_BINDING_BYTES,
    JevboxPreparationBindingError,
    load_jevbox_preparation_binding,
    load_optional_jevbox_preparation_binding,
)


def binding_value() -> dict:
    digest = hashlib.sha256(b"synthetic source").hexdigest()
    return {
        "schema_version": 1,
        "context": {
            "actor_user_id": "synthetic-owner",
            "owner_user_id": "synthetic-owner",
            "storage_user_id": "synthetic-owner",
            "momo_organization_id": "synthetic-momo",
            "jevbox_organization_id": "synthetic-jevbox",
            "source_client_id": "synthetic-client",
            "document_ids": ["synthetic-document"],
            "source_pins": [{"document_id": "synthetic-document", "sha256": digest}],
            "expected_packet_sha256": hashlib.sha256(b"synthetic packet").hexdigest(),
            "expected_reviewed_by": "synthetic-reviewer",
            "expected_reviewed_at": "2026-10-04T12:00:00+00:00",
            "review_expires_at": "2026-10-04T13:00:00+00:00",
            "owner_scope_active": True,
        },
    }


def write_binding(path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def test_loads_closed_context_with_owner_and_source_pins(tmp_path):
    path = tmp_path / "binding.json"
    write_binding(path, binding_value())
    loaded = load_jevbox_preparation_binding(str(path))
    assert loaded.context.owner_user_id == "synthetic-owner"
    assert loaded.context.document_ids == ("synthetic-document",)
    assert loaded.context.source_pins[0][1] == binding_value()["context"]["source_pins"][0]["sha256"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra="unexpected"),
        lambda value: value["context"].update(owner_user_id="other-owner"),
        lambda value: value["context"].update(review_expires_at="2026-10-03T11:00:00+00:00"),
        lambda value: value["context"].update(source_pins=[]),
    ],
)
def test_rejects_malformed_or_cross_owner_binding_without_echoing_contents(tmp_path, mutate):
    value = binding_value()
    mutate(value)
    path = tmp_path / "binding.json"
    write_binding(path, value)
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_jevbox_preparation_binding(str(path))


def test_rejects_duplicate_json_keys_and_oversized_binding(tmp_path):
    path = tmp_path / "binding.json"
    path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_jevbox_preparation_binding(str(path))
    path.write_bytes(b" " * (MAX_BINDING_BYTES + 1))
    path.chmod(0o600)
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_jevbox_preparation_binding(str(path))


def test_large_json_integer_keeps_fixed_binding_error(tmp_path):
    path = tmp_path / "binding.json"
    path.write_bytes(b'{"schema_version":' + b"1" * 5000 + b"}")
    path.chmod(0o600)
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_jevbox_preparation_binding(str(path))


def test_optional_binding_is_absent_by_default_and_empty_or_missing_path_fails_closed(monkeypatch, tmp_path):
    monkeypatch.delenv("MOMOBOT_JEVBOX_PREPARATION_FILE", raising=False)
    assert load_optional_jevbox_preparation_binding() is None
    monkeypatch.setenv("MOMOBOT_JEVBOX_PREPARATION_FILE", "")
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_optional_jevbox_preparation_binding()
    missing = tmp_path / "missing.json"
    monkeypatch.setenv("MOMOBOT_JEVBOX_PREPARATION_FILE", str(missing))
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_optional_jevbox_preparation_binding()


def test_rejects_group_writable_startup_binding(tmp_path):
    path = tmp_path / "binding.json"
    write_binding(path, binding_value())
    path.chmod(0o620)
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_jevbox_preparation_binding(str(path))


def test_rejects_symlink_and_nonregular_fifo_without_blocking(tmp_path):
    target = tmp_path / "target.json"
    write_binding(target, binding_value())
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_jevbox_preparation_binding(str(link))
    fifo = tmp_path / "binding.fifo"
    os.mkfifo(fifo, stat.S_IRUSR | stat.S_IWUSR)
    with pytest.raises(JevboxPreparationBindingError, match="^binding_invalid$"):
        load_jevbox_preparation_binding(str(fifo))
