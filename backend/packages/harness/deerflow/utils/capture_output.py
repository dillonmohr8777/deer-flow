"""Write browser captures without following sandbox-controlled filesystem links."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4


def write_capture_output(directory: Path, name: str, content: bytes, *, collision_probes: int = 1000) -> str:
    """Pin each directory and exclusively create a new capture; never overwrite.

    Both existing and dangling links count as collisions. Descriptor-relative
    traversal keeps a swapped ancestor from redirecting the host-side write.
    Platforms without the required no-follow primitives fail closed.
    """
    if not directory.is_absolute() or ".." in directory.parts or not name or Path(name).name != name or name in (".", ".."):
        raise ValueError("Invalid capture output path")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY") or os.open not in os.supports_dir_fd or os.mkdir not in os.supports_dir_fd:
        raise OSError("Secure capture output is unavailable on this platform")
    handles: list[int] = []
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        handles.append(os.open(directory.anchor, flags))
        for component in directory.parts[1:]:
            try:
                os.mkdir(component, 0o700, dir_fd=handles[-1])
            except FileExistsError:
                pass
            handles.append(os.open(component, flags, dir_fd=handles[-1]))
        parent = handles[-1]
        path = Path(name)
        for index in range(collision_probes + 2):
            candidate = name if index == 0 else f"{path.stem}-{index}{path.suffix}"
            if index > collision_probes:
                candidate = f"{path.stem}-{uuid4().hex}{path.suffix}"
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            except FileExistsError:
                continue
            with os.fdopen(fd, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            return candidate
        raise FileExistsError("Capture output directory is saturated")
    finally:
        for fd in reversed(handles):
            os.close(fd)
