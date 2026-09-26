"""Encrypted off-machine backup of the live gateway volume and, when the
stack runs Postgres, the live database.

1. Online-safe snapshot of the volume into a throwaway volume (backup_volume.py).
2. Tar the snapshot, encrypt it with AES-256-GCM, write it to a synced folder
   (OneDrive by default), plus a receipt with hashes and row counts.
3. If MOMOBOT_BACKUP_POSTGRES_CONTAINER is set (the VPS kit's Postgres
   deployment), pg_dump the live database over its own container (no network
   hop, no password needed thanks to the official image's local-socket trust
   default) and encrypt that too. Users, threads, checkpoints and run_events
   live there, not in the gateway volume, once the stack is on Postgres.
4. Read every encrypted file back, decrypt, and compare the plaintext hash
   (restore check).
5. Keep the newest KEEP copies of each.

The 32-byte key lives outside every synced folder; it is created on first run
and never printed. Keep a second copy of it in a password manager, or the
backups can't be restored if this machine dies.

    python offsite_backup.py                 back up now
    python offsite_backup.py --restore FILE  decrypt FILE (volume tar or
                                              postgres dump) to a local temp
                                              file for a restore
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import secrets
import subprocess
import sys

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = pathlib.Path(__file__).resolve().parent
KEY = pathlib.Path(os.environ.get("MOMOBOT_BACKUP_KEY", r"C:\Users\dillo\Documents\Qwen\.secrets\momobot-backup.key"))
DEST = pathlib.Path(os.environ.get("MOMOBOT_BACKUP_DEST", r"C:\Users\dillo\OneDrive\MomoBot-Backups"))
VOLUME = os.environ.get("MOMOBOT_BACKUP_VOLUME", "deer-flow_gateway-data")
IMAGE = os.environ.get("MOMOBOT_BACKUP_IMAGE", "deer-flow-gateway:momentum-m3b-20260923")
KEEP = int(os.environ.get("MOMOBOT_BACKUP_KEEP", "14"))
# Empty means no Postgres to back up (e.g. the PC's SQLite stack): dump_postgres()
# returns None and the receipt's "postgres" field stays null, same as before this
# existed. Set only by backup.sh, and only when .env has a POSTGRES_PASSWORD.
PG_CONTAINER = os.environ.get("MOMOBOT_BACKUP_POSTGRES_CONTAINER", "")
PG_USER = os.environ.get("MOMOBOT_BACKUP_POSTGRES_USER", "deerflow")
PG_DB = os.environ.get("MOMOBOT_BACKUP_POSTGRES_DB", "deerflow")
MAGIC = b"MOMOBK1\n"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def docker(*args, **kw):
    return subprocess.run(["docker", *args], check=True, capture_output=True, creationflags=NO_WINDOW, **kw)


def load_key() -> bytes:
    if not KEY.exists():
        KEY.parent.mkdir(parents=True, exist_ok=True)
        KEY.write_bytes(secrets.token_bytes(32))
    key = KEY.read_bytes()
    if len(key) != 32:
        sys.exit("backup key must be 32 bytes")
    return key


def _encrypt_to_file(plain: bytes, key: bytes, path: pathlib.Path) -> bytes:
    """Encrypt `plain`, write it to `path`, and return the bytes written."""
    nonce = secrets.token_bytes(12)
    blob = MAGIC + nonce + AESGCM(key).encrypt(nonce, plain, MAGIC)
    path.write_bytes(blob)
    return blob


def _decrypt_bytes(blob: bytes, key: bytes) -> bytes:
    return AESGCM(key).decrypt(blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:], MAGIC)


def _restore_checked(plain: bytes, key: bytes, path: pathlib.Path) -> bool:
    """Read `path` back from disk and confirm it decrypts to `plain`."""
    return hashlib.sha256(_decrypt_bytes(path.read_bytes(), key)).hexdigest() == hashlib.sha256(plain).hexdigest()


def dump_postgres() -> bytes | None:
    """pg_dump the live database over the running container's own socket.

    Returns None when MOMOBOT_BACKUP_POSTGRES_CONTAINER is unset, so a
    SQLite deployment's backup is unaffected. When it is set, a failed dump
    exits loudly instead of silently leaving the database out of a receipt
    that says PASS.
    """
    if not PG_CONTAINER:
        return None
    try:
        return docker("exec", PG_CONTAINER, "pg_dump", "-U", PG_USER, "-d", PG_DB, "--format=custom").stdout
    except subprocess.CalledProcessError as exc:
        sys.exit(f"postgres dump failed ({PG_CONTAINER}): {exc.stderr.decode(errors='replace')}")


def backup() -> dict:
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp = f"deer-flow-offsite-{stamp}"
    docker("volume", "create", tmp)
    try:
        snap = docker("run", "--rm", "--network", "none",
                      "--mount", f"type=volume,source={VOLUME},target=/source,readonly",
                      "--mount", f"type=volume,source={tmp},target=/backup",
                      "--mount", f"type=bind,source={HERE / 'backup_volume.py'},target=/tmp/backup.py,readonly",
                      "--entrypoint", "python", IMAGE, "/tmp/backup.py")
        receipt = json.loads(snap.stdout.decode().strip().splitlines()[-1])
        if receipt.get("state") != "PASS":
            sys.exit(f"snapshot failed: {receipt}")
        tar = docker("run", "--rm", "--network", "none", "--mount", f"type=volume,source={tmp},target=/b,readonly",
                     "--entrypoint", "tar", IMAGE, "czf", "-", "-C", "/b", ".").stdout
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", tmp], capture_output=True, creationflags=NO_WINDOW)

    key = load_key()
    DEST.mkdir(parents=True, exist_ok=True)
    out = DEST / f"gateway-data-{stamp}.tgz.enc"
    back = _encrypt_to_file(tar, key, out)
    ok = _restore_checked(tar, key, out)

    postgres_result = None
    pg_dump_bytes = dump_postgres()
    if pg_dump_bytes is not None:
        pg_out = DEST / f"postgres-{stamp}.dump.enc"
        pg_back = _encrypt_to_file(pg_dump_bytes, key, pg_out)
        pg_ok = _restore_checked(pg_dump_bytes, key, pg_out)
        postgres_result = {"state": "PASS" if pg_ok else "FAIL", "file": pg_out.name,
                            "encrypted_bytes": len(pg_back), "dump_sha256": hashlib.sha256(pg_dump_bytes).hexdigest()}
        ok = ok and pg_ok

    result = {"state": "PASS" if ok else "FAIL", "file": out.name, "encrypted_bytes": len(back),
              "tar_sha256": hashlib.sha256(tar).hexdigest(), "snapshot": receipt, "postgres": postgres_result}
    (DEST / f"gateway-data-{stamp}.receipt.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    for old in sorted(DEST.glob("gateway-data-*.tgz.enc"))[:-KEEP]:
        old.unlink()
        old.with_name(old.name.replace(".tgz.enc", ".receipt.json")).unlink(missing_ok=True)
    for old in sorted(DEST.glob("postgres-*.dump.enc"))[:-KEEP]:
        old.unlink()
    return result


def restore(path: pathlib.Path) -> None:
    blob = path.read_bytes()
    if not blob.startswith(MAGIC):
        sys.exit("not a MomoBot backup")
    plain = _decrypt_bytes(blob, load_key())
    # Never decrypt into the synced folder: plaintext would upload.
    target = pathlib.Path(os.environ.get("TEMP", "/tmp")) / path.with_suffix("").name
    target.write_bytes(plain)
    if path.name.startswith("postgres-"):
        print(f"decrypted to {target}; restore into a running Postgres with: "
              f"docker cp {target} <postgres-container>:/tmp/{target.name} && "
              f"docker exec <postgres-container> pg_restore --clean --if-exists -U <user> -d <db> /tmp/{target.name}")
    else:
        print(f"decrypted to {target}; load it into an EMPTY volume with: docker run --rm -v <empty-volume>:/b -v {target.parent}:/in alpine tar xzf /in/{target.name} -C /b")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", type=pathlib.Path)
    a = ap.parse_args()
    if a.restore:
        restore(a.restore)
    else:
        r = backup()
        print(json.dumps({k: r[k] for k in ("state", "file", "encrypted_bytes")}))
        sys.exit(0 if r["state"] == "PASS" else 1)
