"""Explicit owner command to publish a coherent saved Brain generation on POSIX."""

import argparse
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from brain_readonly_adapter import (
    ConfigurationError,
    _is_sha256,
    _sha256,
    generation_id,
    load_generation,
    load_snapshot_pair,
    load_snapshot_renderer,
    parse_current_pointer,
    read_current_pointer,
    read_snapshot_file,
    snapshot_directory,
    snapshot_json,
    snapshot_timestamp,
)


def _fsync_directory(directory):
    directory = snapshot_directory(directory)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_private(path, raw):
    snapshot_directory(path.parent)
    descriptor = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600
    )
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def _publication_lock(root):
    # Exclusive creation also rejects symlinks; crash leftovers require owner review.
    path = root / ".publish.lock"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        yield
    finally:
        identity = os.fstat(descriptor)
        os.close(descriptor)
        current = path.lstat()
        if (identity.st_dev, identity.st_ino) != (current.st_dev, current.st_ino):
            raise ConfigurationError()
        path.unlink()


def publish(source_directory, snapshot_root, renderer_sha256):
    """Validate before commit; only current.json selects a complete generation."""
    if not _is_sha256(renderer_sha256):
        raise ConfigurationError()
    source = snapshot_directory(source_directory)
    root = snapshot_directory(snapshot_root)
    with _publication_lock(root):
        renderer, renderer_hash = load_snapshot_renderer(root, renderer_sha256)
        previous_pointer = read_current_pointer(root)
        previous = None
        if previous_pointer is not None:
            previous = load_generation(
                root, parse_current_pointer(previous_pointer), renderer, renderer_hash
            )
        state, payloads = load_snapshot_pair(source, renderer)
        observed_at = state[2]
        if previous and snapshot_timestamp(observed_at) < snapshot_timestamp(
            previous[2]
        ):
            raise ConfigurationError()
        metadata = {
            "schemaVersion": 1,
            "sourceObservedAt": observed_at,
            "rendererSha256": renderer_hash,
            "files": {name: _sha256(raw) for name, raw in payloads.items()},
        }
        generation = generation_id(metadata)
        receipt = {
            "generation": generation,
            "sourceObservedAt": observed_at,
            "changed": previous is None or previous[3] != generation,
        }
        if not receipt["changed"]:
            if read_current_pointer(root) != previous_pointer:
                raise ConfigurationError()
            return receipt
        generations = root / "generations"
        generations.mkdir(mode=0o700, exist_ok=True)
        snapshot_directory(generations)
        destination = generations / generation
        if not destination.exists():
            stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=generations))
            for name, raw in {
                **payloads,
                "manifest.json": snapshot_json({**metadata, "generation": generation}),
            }.items():
                _write_private(stage / name, raw)
            _fsync_directory(stage)
            os.rename(stage, destination)
        else:
            _fsync_directory(destination)
        _fsync_directory(generations)
        load_generation(root, generation, renderer, renderer_hash)
        temporary_pointer = root / f".current-{uuid4().hex}.tmp"
        try:
            _write_private(
                temporary_pointer,
                snapshot_json({"schemaVersion": 1, "generation": generation}),
            )
            _fsync_directory(root)
            if (
                read_current_pointer(root) != previous_pointer
                or _sha256(read_snapshot_file(root / "brain.py")) != renderer_hash
            ):
                raise ConfigurationError()
            os.replace(temporary_pointer, root / "current.json")
            _fsync_directory(root)
        finally:
            temporary_pointer.unlink(missing_ok=True)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--renderer-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = publish(args.source_dir, args.snapshot_dir, args.renderer_sha256)
    except Exception:
        print("Brain snapshot publication failed.", file=sys.stderr)
        return 2
    print(snapshot_json(receipt).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
