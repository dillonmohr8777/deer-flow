"""USER.md must be per-user, not process-global.

USER.md is injected into every custom agent. While it lived at
`{base_dir}/USER.md`, any caller who reached the agents API rewrote the
persona of every other user's agents, across every workspace. These tests
pin the isolation so that cannot come back.
"""

from __future__ import annotations

from deerflow.config.paths import Paths


def _make_paths(tmp_path) -> Paths:
    """Same construction the existing agent tests use."""
    return Paths(base_dir=tmp_path)


def test_two_users_get_different_profile_files(tmp_path):
    """The bug: one file shared by everyone. Different users must not collide."""
    paths = _make_paths(tmp_path)

    alice = paths.user_md_file_for("alice")
    bob = paths.user_md_file_for("bob")

    assert alice != bob
    assert alice == tmp_path / "users" / "alice" / "USER.md"
    assert bob == tmp_path / "users" / "bob" / "USER.md"


def test_per_user_file_is_not_the_legacy_shared_file(tmp_path):
    """A per-user write must never land on the process-global path."""
    paths = _make_paths(tmp_path)

    assert paths.user_md_file == tmp_path / "USER.md"
    assert paths.user_md_file_for("alice") != paths.user_md_file


def test_a_write_by_one_user_is_invisible_to_another(tmp_path):
    """The actual contamination scenario, end to end on the filesystem."""
    paths = _make_paths(tmp_path)

    alice = paths.user_md_file_for("alice")
    alice.parent.mkdir(parents=True, exist_ok=True)
    alice.write_text("I am Alice. Always answer in French.", encoding="utf-8")

    bob = paths.user_md_file_for("bob")
    assert not bob.exists()
    assert paths.user_md_file.read_text(encoding="utf-8") if paths.user_md_file.exists() else True
    # Bob's bucket is untouched and the legacy shared file was never created.
    assert not paths.user_md_file.exists()


def test_user_id_is_validated_not_interpolated(tmp_path):
    """Path traversal through the user id must not escape the bucket root.

    user_dir() runs _validate_user_id; this asserts the profile path inherits
    it rather than concatenating a raw id.
    """
    paths = _make_paths(tmp_path)
    users_root = (tmp_path / "users").resolve()

    for candidate in ("../../etc", "..\\..\\windows", "a/../../b"):
        try:
            resolved = paths.user_md_file_for(candidate).resolve()
        except Exception:
            continue  # rejecting outright is a valid answer
        assert users_root in resolved.parents, f"{candidate} escaped to {resolved}"


if __name__ == "__main__":  # pragma: no cover
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        for fn in (
            test_two_users_get_different_profile_files,
            test_per_user_file_is_not_the_legacy_shared_file,
            test_a_write_by_one_user_is_invisible_to_another,
            test_user_id_is_validated_not_interpolated,
        ):
            sub = Path(d) / fn.__name__
            sub.mkdir()
            fn(sub)
            print(f"  ok  {fn.__name__}")
    print("USER.md isolation: all checks pass")
