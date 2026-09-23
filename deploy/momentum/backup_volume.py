"""Snapshot /source into an empty /backup, safe while the stack is running.

SQLite databases go through the online backup API (consistent even with a live
writer and uncheckpointed WAL); their -wal/-shm files are not copied. Every other
file is copied and hash-verified. Prints and writes a receipt without file contents.
"""

import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

source, target = Path("/source"), Path("/backup")
assert not any(target.iterdir()), "Backup volume must be empty"


def is_sqlite(p: Path) -> bool:
    if p.is_symlink() or not p.is_file() or p.stat().st_size < 100:
        return False
    with p.open("rb") as f:
        return f.read(16) == b"SQLite format 3\x00"


def sha(p: Path) -> bytes:
    with p.open("rb") as f:
        return hashlib.file_digest(f, "sha256").digest()


dbs = {p for p in source.rglob("*") if is_sqlite(p)}
sidecars = {p.with_name(p.name + s) for p in dbs for s in ("-wal", "-shm", "-journal")}
files = size = 0
databases = {}
for original in sorted(source.rglob("*")):
    copy = target / original.relative_to(source)
    if original.is_symlink():
        copy.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(os.readlink(original), copy)
    elif original.is_dir():
        copy.mkdir(parents=True, exist_ok=True)
    elif original in sidecars:
        continue
    elif original in dbs:
        copy.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(f"file:{original}?mode=ro", uri=True)
        dst = sqlite3.connect(copy)
        src.backup(dst)
        src.close()
        dst.execute("PRAGMA journal_mode=DELETE")
        check = dst.execute("PRAGMA integrity_check").fetchone()[0]
        assert check == "ok", f"integrity_check failed for {original}: {check}"
        tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        databases[str(original.relative_to(source))] = {
            "integrity": check,
            "rows": {t: dst.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in sorted(tables)},
        }
        dst.close()
    elif original.is_file():
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, copy)
        assert sha(original) == sha(copy), f"Backup content mismatch: {original}"
        files += 1
        size += original.stat().st_size

result = {"state": "PASS", "files_verified": files, "bytes_verified": size, "databases": databases}
(target / ".deployment-backup-receipt.json").write_text(json.dumps(result, indent=1))
print(json.dumps({"state": "PASS", "files_verified": files, "bytes_verified": size, "databases": {k: sum(v["rows"].values()) for k, v in databases.items()}}))
