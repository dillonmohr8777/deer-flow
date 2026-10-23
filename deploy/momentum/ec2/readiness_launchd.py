"""Generate two local check plists; loading them is a separate reviewed step."""

from __future__ import annotations

import argparse
from pathlib import Path
import plistlib


def write_plists(
    checkout: Path, python: Path, pnpm: Path, output: Path, receipts: Path
) -> None:
    checkout, python, pnpm = checkout.absolute(), python.absolute(), pnpm.absolute()
    for required in (checkout / "deploy/momentum/ec2/readiness_check.py", python, pnpm):
        if not required.is_file():
            raise ValueError(f"Missing prerequisite: {required}")
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
    for mode, hour in (("tenant", 13), ("restore", 5)):
        label = f"com.dillon.momo-readiness-{mode}"
        payload = {
            "Label": label,
            "ProgramArguments": [
                str(python),
                str(checkout / "deploy/momentum/ec2/readiness_check.py"),
                mode,
                "--python",
                str(python),
                "--pnpm",
                str(pnpm),
                "--receipts",
                str(receipts / "ledger.jsonl"),
            ],
            "WorkingDirectory": str(checkout),
            "EnvironmentVariables": {
                "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
                "AWS_PAGER": "",
            },
            "StartCalendarInterval": {"Hour": hour, "Minute": 15},
            "ProcessType": "Background",
            "Umask": 0o077,
            "StandardOutPath": str(receipts / f"{mode}.log"),
            "StandardErrorPath": str(receipts / f"{mode}.err"),
        }
        with (output / f"{label}.plist").open("wb") as stream:
            plistlib.dump(payload, stream)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--pnpm", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipts", type=Path, required=True)
    args = parser.parse_args()
    write_plists(**vars(args))
