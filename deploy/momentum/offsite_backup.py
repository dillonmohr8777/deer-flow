"""Encrypted off-machine backup of the live gateway volume.

1. Online-safe snapshot of the volume into a throwaway volume (backup_volume.py).
2. Tar the snapshot, encrypt it with AES-256-GCM, write it to a synced folder
   (OneDrive by default), plus a receipt with hashes and row counts.
3. Read the file back, decrypt, and compare the plaintext hash (restore check).
4. Keep the newest KEEP copies.

The 32-byte key lives outside every synced folder; it is created on first run
and never printed. Keep a second copy of it in a password manager, or the
backups can't be restored if this machine dies.

    python offsite_backup.py                 back up now
    python offsite_backup.py --restore FILE  decrypt FILE to a local temp .tgz for a restore
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

    nonce = secrets.token_bytes(12)
    blob = MAGIC + nonce + AESGCM(load_key()).encrypt(nonce, tar, MAGIC)
    DEST.mkdir(parents=True, exist_ok=True)
    out = DEST / f"gateway-data-{stamp}.tgz.enc"
    out.write_bytes(blob)

    # Restore check: read it back from disk and decrypt.
    back = out.read_bytes()
    plain = AESGCM(load_key()).decrypt(back[len(MAGIC):len(MAGIC) + 12], back[len(MAGIC) + 12:], MAGIC)
    ok = hashlib.sha256(plain).hexdigest() == hashlib.sha256(tar).hexdigest()
    result = {"state": "PASS" if ok else "FAIL", "file": out.name, "encrypted_bytes": len(back),
              "tar_sha256": hashlib.sha256(tar).hexdigest(), "snapshot": receipt}
    (DEST / f"gateway-data-{stamp}.receipt.json").write_text(json.dumps(result, indent=1), encoding="utf-8")

    for old in sorted(DEST.glob("gateway-data-*.tgz.enc"))[:-KEEP]:
        old.unlink()
        old.with_name(old.name.replace(".tgz.enc", ".receipt.json")).unlink(missing_ok=True)
    return result


def restore(path: pathlib.Path) -> None:
    blob = path.read_bytes()
    if not blob.startswith(MAGIC):
        sys.exit("not a MomoBot backup")
    plain = AESGCM(load_key()).decrypt(blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:], MAGIC)
    # Never decrypt into the synced folder: plaintext would upload.
    target = pathlib.Path(os.environ.get("TEMP", "/tmp")) / path.with_suffix("").name
    target.write_bytes(plain)
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
