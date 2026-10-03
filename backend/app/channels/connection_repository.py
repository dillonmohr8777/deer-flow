"""Shared host configuration for user-owned channel credential storage."""

from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.channel_connections import ChannelConnectionRepository, ChannelCredentialCipher


def create_channel_connection_repository(session_factory: async_sessionmaker[AsyncSession]) -> ChannelConnectionRepository:
    """Use only the explicit protected host key; absence keeps identity-only mode.

    The key is read when a repository is constructed, never generated, persisted,
    logged, or substituted with provider credentials. Restart the Gateway after
    host configuration changes; existing repositories retain their cipher.
    """
    key = os.environ.get("CHANNEL_CONNECTIONS_ENCRYPTION_KEY", "")
    cipher = ChannelCredentialCipher.from_key(key) if key.strip() else None
    return ChannelConnectionRepository(session_factory, cipher=cipher)
