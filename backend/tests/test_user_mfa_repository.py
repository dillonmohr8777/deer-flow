"""Tests for the UserMfaRepository."""

from __future__ import annotations

import pytest
import pytest_asyncio

from deerflow.config.database_config import DatabaseConfig
from deerflow.persistence.engine import close_engine, get_session_factory, init_engine_from_config
from deerflow.persistence.user.model import UserRow
from deerflow.persistence.user_mfa import UserMfaRepository


@pytest_asyncio.fixture(autouse=True)
async def _close_persistence_engine():
    yield
    await close_engine()


async def _make_repo(tmp_path, *, user_ids: tuple[str, ...] = ("user-1",)) -> UserMfaRepository:
    """A repository backed by a fresh SQLite DB, seeded with a ``users`` row per
    id -- ``user_mfa.user_id`` is FK-constrained (CASCADE on user delete)."""
    await init_engine_from_config(DatabaseConfig(backend="sqlite", sqlite_dir=str(tmp_path)))
    session_factory = get_session_factory()
    assert session_factory is not None
    async with session_factory() as session:
        session.add_all([UserRow(id=user_id, email=f"{user_id}@example.com") for user_id in user_ids])
        await session.commit()
    return UserMfaRepository(session_factory)


@pytest.mark.asyncio
async def test_get_returns_none_when_no_row(tmp_path):
    repo = await _make_repo(tmp_path)
    assert await repo.get("user-1") is None


@pytest.mark.asyncio
async def test_start_enrollment_creates_a_pending_unconfirmed_row(tmp_path):
    repo = await _make_repo(tmp_path)
    record = await repo.start_enrollment("user-1", "ciphertext-1")
    assert record["user_id"] == "user-1"
    assert record["secret_encrypted"] == "ciphertext-1"
    assert record["enabled_at"] is None
    assert record["recovery_codes"] == []

    fetched = await repo.get("user-1")
    assert fetched == record


@pytest.mark.asyncio
async def test_restarting_enrollment_overwrites_the_previous_secret(tmp_path):
    repo = await _make_repo(tmp_path)
    await repo.start_enrollment("user-1", "ciphertext-1")
    record = await repo.start_enrollment("user-1", "ciphertext-2")
    assert record["secret_encrypted"] == "ciphertext-2"
    assert record["enabled_at"] is None


@pytest.mark.asyncio
async def test_confirm_enrollment_requires_a_pending_row(tmp_path):
    repo = await _make_repo(tmp_path)
    with pytest.raises(LookupError):
        await repo.confirm_enrollment("user-1", ["hash-a"])


@pytest.mark.asyncio
async def test_confirm_enrollment_enables_and_stores_hashed_codes(tmp_path):
    repo = await _make_repo(tmp_path)
    await repo.start_enrollment("user-1", "ciphertext-1")
    record = await repo.confirm_enrollment("user-1", ["hash-a", "hash-b"])
    assert record["enabled_at"] is not None
    assert record["recovery_codes"] == [
        {"hash": "hash-a", "used_at": None},
        {"hash": "hash-b", "used_at": None},
    ]


@pytest.mark.asyncio
async def test_disable_deletes_the_row(tmp_path):
    repo = await _make_repo(tmp_path)
    await repo.start_enrollment("user-1", "ciphertext-1")
    await repo.confirm_enrollment("user-1", ["hash-a"])

    assert await repo.disable("user-1") is True
    assert await repo.get("user-1") is None
    # Disabling again (nothing to disable) is a clean no-op, not an error.
    assert await repo.disable("user-1") is False


@pytest.mark.asyncio
async def test_mark_recovery_code_used_is_single_use(tmp_path):
    repo = await _make_repo(tmp_path)
    await repo.start_enrollment("user-1", "ciphertext-1")
    await repo.confirm_enrollment("user-1", ["hash-a", "hash-b"])

    assert await repo.mark_recovery_code_used("user-1", "hash-a") is True
    record = await repo.get("user-1")
    used_entry = next(c for c in record["recovery_codes"] if c["hash"] == "hash-a")
    unused_entry = next(c for c in record["recovery_codes"] if c["hash"] == "hash-b")
    assert used_entry["used_at"] is not None
    assert unused_entry["used_at"] is None

    # Reusing the same code fails: it is already spent.
    assert await repo.mark_recovery_code_used("user-1", "hash-a") is False
    # The other, unused code still works.
    assert await repo.mark_recovery_code_used("user-1", "hash-b") is True


@pytest.mark.asyncio
async def test_mark_recovery_code_used_rejects_unknown_hash_and_disabled_user(tmp_path):
    repo = await _make_repo(tmp_path)
    assert await repo.mark_recovery_code_used("no-such-user", "hash-a") is False

    await repo.start_enrollment("user-1", "ciphertext-1")
    # Pending (not yet confirmed / enabled) rows never validate a recovery code.
    assert await repo.mark_recovery_code_used("user-1", "hash-a") is False

    await repo.confirm_enrollment("user-1", ["hash-a"])
    assert await repo.mark_recovery_code_used("user-1", "hash-does-not-exist") is False
