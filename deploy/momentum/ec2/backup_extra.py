"""Add the EC2 bind mounts and non-secret recovery settings to a backup stage."""

import json
import subprocess
import sys
import tarfile
from pathlib import Path

MOUNTS = [
    f"data/{name}" for name in ("skills", "admission", "lobby-notes", "brand", "evals")
] + [
    "code/momo_guard.py",
    "code/momo_protocol.py",
    "code/brain_readonly_adapter.py",
]
SETTINGS = {
    "settings.env": (
        "MOMOBOT_DOMAIN",
        "MOMOBOT_ACME_EMAIL",
        "MOMENTUM_GATEWAY_IMAGE",
        "MOMENTUM_FRONTEND_IMAGE",
        "GATEWAY_ENABLE_DOCS",
    ),
    "frontend.env": ("MOMO_DAILY_CLOUD_OWNER_USER_ID",),
}


def snapshot(deploy: Path, stage: Path) -> None:
    def keep(member: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if member.issym() or member.islnk():
            raise ValueError(f"EC2 backup refuses symlink/hardlink: {member.name}")
        name = Path(member.name).name
        return None if name.endswith(".env") or name.startswith(".env.") else member

    with tarfile.open(stage / "ec2-mounts.tgz", "w:gz") as archive:
        for name in MOUNTS:
            for parent in (deploy / name).parents:
                if parent == deploy:
                    break
                if parent.is_symlink():
                    raise ValueError(f"EC2 backup refuses symlink ancestor: {parent}")
            archive.add(deploy / name, arcname=name, filter=keep)
    getter = Path(__file__).resolve().parents[1] / "vps/dotenv-get.sh"
    settings = {}
    for filename, keys in SETTINGS.items():
        if not (deploy / filename).is_file():
            raise FileNotFoundError(deploy / filename)
        settings[filename] = {
            key: subprocess.check_output(
                ["bash", str(getter), str(deploy / filename), key], text=True
            ).strip()
            for key in keys
        }
    (stage / "ec2-recovery.json").write_text(
        json.dumps(settings, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    snapshot(Path(sys.argv[1]), Path(sys.argv[2]))
