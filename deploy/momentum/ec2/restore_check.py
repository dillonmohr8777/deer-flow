"""Validate an EC2 nightly backup in private temporary storage; never start services."""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path, PurePosixPath

REQUIRED = {
    "gateway-data.tgz",
    "config.yaml",
    "extensions_config.json",
    "redis.rdb",
    "ec2-mounts.tgz",
    "ec2-recovery.json",
}
# Bound unattended disk use across the outer archive and both nested archives.
MAX_BYTES = 4 * 1024**3
MAX_MEMBERS = 100_000


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name or "\x00" in name:
        raise ValueError("unsafe archive path")
    return path


def unpack(source, target, budget=None):
    """Restore regular entries first, then validate strictly internal relative links."""
    budget = budget if budget is not None else [MAX_BYTES, MAX_MEMBERS]
    seen = set()
    links = []
    with tarfile.open(source, "r:gz") as archive:
        for member in archive:
            name = safe_name(member.name)
            budget[1] -= 1
            if budget[1] < 0 or name in seen:
                raise ValueError("archive member limit or duplicate path")
            seen.add(name)
            if not (member.isfile() or member.isdir() or member.issym()):
                raise ValueError("archive hardlinks and special files are forbidden")
            dest = target / str(name)
            if member.issym():
                link = member.linkname
                if (
                    not link
                    or PurePosixPath(link).is_absolute()
                    or "\\" in link
                    or "\x00" in link
                ):
                    raise ValueError("unsafe symlink target")
                links.append((name, link))
            elif member.isdir():
                dest.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                budget[0] -= member.size
                if member.size < 0 or budget[0] < 0:
                    raise ValueError("archive exceeds restore size budget")
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with archive.extractfile(member) as src, dest.open("xb") as dst:
                    shutil.copyfileobj(src, dst)

    # A link can never be an extraction parent, regardless of archive order.
    link_names = {name for name, _ in links}
    if any(parent in link_names for name in seen for parent in name.parents):
        raise ValueError("archive member has a symlink ancestor")
    for name, link in links:
        dest = target / str(name)
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        dest.symlink_to(link)
    for name, _ in links:
        try:
            (target / str(name)).resolve(strict=True).relative_to(target.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError("symlink is escaping, cyclic or broken") from exc


def verify_manifest(stage):
    actual = {
        p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()
    } - {"MANIFEST.sha256"}
    expected = set()
    for line in (stage / "MANIFEST.sha256").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if not match:
            raise ValueError("invalid manifest line")
        name = str(safe_name(match[2]))
        if name in expected or name not in actual:
            raise ValueError("manifest has duplicate or missing payload")
        expected.add(name)
        with (stage / name).open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != match[1].lower():
                raise ValueError("manifest hash mismatch")
    if expected != actual or not REQUIRED.issubset(actual):
        raise ValueError("manifest does not cover required payloads")
    if any(not (stage / name).stat().st_size for name in REQUIRED):
        raise ValueError("empty required payload")


def verify_databases(gateway):
    receipt = json.loads(
        (gateway / ".deployment-backup-receipt.json").read_text(encoding="utf-8")
    )
    expected = receipt.get("databases")
    if receipt.get("state") != "PASS" or not isinstance(expected, dict) or not expected:
        raise ValueError("missing successful database snapshot receipt")
    actual = set()
    for path in gateway.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as handle:
                if handle.read(16) == b"SQLite format 3\x00":
                    actual.add(path.relative_to(gateway).as_posix())
    if actual != set(expected):
        raise ValueError("SQLite payload differs from snapshot receipt")
    total = 0
    for name, snapshot in expected.items():
        path = gateway / str(safe_name(name))
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)
        ) as conn:
            conn.execute("PRAGMA trusted_schema=OFF")
            if conn.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite integrity check failed")
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            counts = {
                table: conn.execute(
                    'SELECT count(*) FROM "' + table.replace('"', '""') + '"'
                ).fetchone()[0]
                for (table,) in tables
            }
        if snapshot.get("integrity") != "ok" or counts != snapshot.get("rows"):
            raise ValueError("restored row counts differ from snapshot receipt")
        total += sum(counts.values())
    if total <= 0:
        raise ValueError("backup has no recoverable database rows")
    return len(expected), total


def verify_backup(source):
    """Accept only the full EC2 nightly .tgz format, with no caller-supplied target."""
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise ValueError("backup must be a local regular file")
    budget = [MAX_BYTES, MAX_MEMBERS]
    with tempfile.TemporaryDirectory(prefix="momobot-restore-check-") as temp:
        root = Path(temp)
        stage, gateway, mounts = (
            root / name for name in ("stage", "gateway", "mounts")
        )
        for target in (stage, gateway, mounts):
            target.mkdir(mode=0o700)
        unpack(source, stage, budget)
        verify_manifest(stage)
        if not (stage / "config.yaml").read_text(encoding="utf-8").strip():
            raise ValueError("empty gateway config")
        if not isinstance(
            json.loads((stage / "extensions_config.json").read_text(encoding="utf-8")),
            dict,
        ):
            raise ValueError("extensions config must be an object")
        with (stage / "redis.rdb").open("rb") as handle:
            if not re.fullmatch(rb"REDIS\d{4}", handle.read(9)):
                raise ValueError("invalid Redis RDB header")
        recovery = json.loads((stage / "ec2-recovery.json").read_text(encoding="utf-8"))
        for name, keys in {
            "settings.env": {
                "MOMOBOT_DOMAIN",
                "MOMOBOT_ACME_EMAIL",
                "MOMENTUM_GATEWAY_IMAGE",
                "MOMENTUM_FRONTEND_IMAGE",
                "GATEWAY_ENABLE_DOCS",
            },
            "frontend.env": {"MOMO_DAILY_CLOUD_OWNER_USER_ID"},
        }.items():
            values = recovery.get(name)
            if (
                not isinstance(values, dict)
                or set(values) != keys
                or not all(isinstance(v, str) for v in values.values())
            ):
                raise ValueError("invalid EC2 recovery settings")
        unpack(stage / "ec2-mounts.tgz", mounts, budget)
        for name in ("skills", "admission", "lobby-notes", "brand", "evals"):
            if not (mounts / "data" / name).is_dir():
                raise ValueError("missing EC2 data mount")
        for name in ("momo_guard.py", "momo_protocol.py", "brain_readonly_adapter.py"):
            path = mounts / "code" / name
            if not path.is_file() or not path.stat().st_size:
                raise ValueError("missing EC2 code mount")
        unpack(stage / "gateway-data.tgz", gateway, budget)
        databases, rows = verify_databases(gateway)
    return {
        "state": "PASS",
        "format": "ec2-nightly-tgz",
        "database_count": databases,
        "row_count": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "backup", type=Path, help="local EC2 nightly .tgz; no downloads or live restore"
    )
    args = parser.parse_args()
    try:
        result = verify_backup(args.backup)
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        sqlite3.Error,
        tarfile.TarError,
        EOFError,
    ):
        # Archive names, SQL diagnostics and config values may contain private data.
        print(
            json.dumps({"state": "FAIL", "error": "backup restore validation failed"})
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
