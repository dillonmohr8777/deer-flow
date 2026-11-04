"""User repository interface for abstracting database operations."""

from abc import ABC, abstractmethod

from app.gateway.auth.models import User


class UserNotFoundError(LookupError):
    """Raised when a user repository operation targets a non-existent row.

    Subclass of :class:`LookupError` so callers that already catch
    ``LookupError`` for "missing entity" can keep working unchanged,
    while specific call sites can pin to this class to distinguish
    "concurrent delete during update" from other lookups.
    """


class UserRepository(ABC):
    """Abstract interface for user data storage.

    Implement this interface to support different storage backends
    (SQLite)
    """

    @abstractmethod
    async def create_user(self, user: User) -> User:
        """Create a new user.

        Args:
            user: User object to create

        Returns:
            Created User with ID assigned. ``email`` is the canonical
            (lowercase) stored form, which may differ in case from what was
            passed in -- implementations mutate the input ``user`` in place
            to reflect this rather than returning a fresh object.

        Raises:
            ValueError: If email already exists
        """
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> User | None:
        """Get user by ID.

        Args:
            user_id: User UUID as string

        Returns:
            User if found, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_email(self, email: str) -> User | None:
        """Get user by email.

        Args:
            email: User email address

        Returns:
            User if found, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def update_user(self, user: User) -> User:
        """Update an existing user.

        Args:
            user: User object with updated fields

        Returns:
            Updated User. ``email`` is the canonical (lowercase) stored
            form -- implementations mutate the input ``user`` in place to
            reflect this rather than returning a fresh object.

        Raises:
            UserNotFoundError: If no row exists for ``user.id``. This is
                a hard failure (not a no-op) so callers cannot mistake a
                concurrent-delete race for a successful update.
        """
        raise NotImplementedError

    @abstractmethod
    async def count_users(self) -> int:
        """Return total number of registered users."""
        raise NotImplementedError

    @abstractmethod
    async def count_admin_users(self) -> int:
        """Return number of users with system_role == 'admin'."""
        raise NotImplementedError

    @abstractmethod
    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        """Get user by OAuth provider and ID.

        Args:
            provider: OAuth provider name (e.g. 'github', 'google')
            oauth_id: User ID from the OAuth provider

        Returns:
            User if found, None otherwise
        """
        raise NotImplementedError

    @abstractmethod
    async def count_users_by_email(self, email: str) -> int:
        """Count accounts whose email matches ``email`` case-insensitively.

        ``get_user_by_email`` resolves to the oldest row when a legacy
        database holds two rows differing only in case; this lets a caller
        that must act on exactly one account detect that ambiguity.
        """
        raise NotImplementedError

    @abstractmethod
    async def link_oauth_identity_if_unlinked(self, user_id: str, provider: str, oauth_id: str) -> User | None:
        """Atomically attach an SSO identity to an active account that has none.

        The write only happens while the row still has no ``oauth_provider`` /
        ``oauth_id`` and is not disabled, so a concurrent link, an admin
        disable or a second callback cannot be overwritten.

        Returns:
            The updated User, or None when the row no longer qualifies.

        Raises:
            ValueError: If the (provider, oauth_id) pair is already linked to
                another account.
        """
        raise NotImplementedError

    @abstractmethod
    async def set_oauth_identity(
        self,
        user_id: str,
        provider: str | None,
        oauth_id: str | None,
        *,
        expected_provider: str | None,
        expected_oauth_id: str | None,
        revoke_sessions: bool,
    ) -> User | None:
        """Set or clear (both None) an account's SSO identity, compare-and-set.

        The write only happens while the row still holds
        ``expected_provider`` / ``expected_oauth_id`` (the identity the caller
        read), so a sign-in that linked the account in between is never
        silently overwritten. ``revoke_sessions`` also bumps ``token_version``
        in the same statement, so sessions issued before the change stop
        working.

        Returns:
            The updated User, or None when the row is gone or no longer holds
            the expected identity.

        Raises:
            ValueError: If the (provider, oauth_id) pair is already linked to
                another account.
        """
        raise NotImplementedError
