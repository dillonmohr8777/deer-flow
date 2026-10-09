"""Browser bytes must never follow sandbox-created links into host files."""

import os

import pytest

from deerflow.community.browser_automation.tools import _write_screenshot
from deerflow.community.browserless.tools import _write_capture_output


@pytest.mark.parametrize("writer", [_write_screenshot, _write_capture_output])
@pytest.mark.parametrize("dangling", [False, True])
def test_capture_does_not_follow_file_symlink(tmp_path, writer, dangling):
    root = tmp_path.resolve()
    outputs = root / "outputs"
    outputs.mkdir()
    outside = root / "outside.png"
    if not dangling:
        outside.write_bytes(b"original")
    (outputs / "capture.png").symlink_to(outside)
    name = writer(outputs, "capture.png", b"screenshot")
    assert outside.exists() is (not dangling)
    if not dangling:
        assert outside.read_bytes() == b"original"
    assert (outputs / name).read_bytes() == b"screenshot"
    assert not (outputs / name).is_symlink()


@pytest.mark.parametrize("writer", [_write_screenshot, _write_capture_output])
@pytest.mark.parametrize("component", ["outputs", "ancestor", ".browser-frames"])
def test_capture_rejects_directory_symlink(tmp_path, writer, component):
    root = tmp_path.resolve()
    outside = root / "outside"
    outside.mkdir()
    if component == "ancestor":
        (root / "ancestor").symlink_to(outside, target_is_directory=True)
        outputs = root / "ancestor" / "outputs"
    elif component == ".browser-frames":
        (root / "outputs").mkdir()
        outputs = root / "outputs" / component
        outputs.symlink_to(outside, target_is_directory=True)
    else:
        outputs = root / component
        outputs.symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        writer(outputs, "capture.png", b"screenshot")
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("writer", [_write_screenshot, _write_capture_output])
def test_capture_preserves_existing_files_and_creates_directories(tmp_path, writer):
    outputs = tmp_path.resolve() / "outputs" / ".browser-frames"
    first = writer(outputs, "capture.png", b"first")
    second = writer(outputs, "capture.png", b"second")
    assert first != second
    assert (outputs / first).read_bytes() == b"first"
    assert (outputs / second).read_bytes() == b"second"


@pytest.mark.parametrize("writer", [_write_screenshot, _write_capture_output])
def test_capture_does_not_overwrite_hardlinked_host_file(tmp_path, writer):
    root = tmp_path.resolve()
    outputs = root / "outputs"
    outputs.mkdir()
    outside = root / "outside.png"
    outside.write_bytes(b"original")
    os.link(outside, outputs / "capture.png")
    name = writer(outputs, "capture.png", b"new")
    assert name != "capture.png"
    assert outside.read_bytes() == b"original"


@pytest.mark.parametrize("writer", [_write_screenshot, _write_capture_output])
def test_capture_pins_directory_during_swap(tmp_path, monkeypatch, writer):
    root = tmp_path.resolve()
    outputs = root / "outputs"
    outputs.mkdir()
    outside = root / "outside"
    outside.mkdir()
    original_open = os.open
    swapped = False

    def swap_on_file_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if path == "capture.png" and not swapped:
            swapped = True
            outputs.rename(root / "original-outputs")
            outputs.symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap_on_file_open)
    monkeypatch.setattr(os, "supports_dir_fd", os.supports_dir_fd | {swap_on_file_open})
    name = writer(outputs, "capture.png", b"new")
    assert list(outside.iterdir()) == []
    assert (root / "original-outputs" / name).read_bytes() == b"new"
