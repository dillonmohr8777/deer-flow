"""Durable per-user preferences; updates touch only explicitly supplied keys."""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from deerflow.persistence.user.model import UserPreferenceRow


class UserPreferencesRepository:
    def __init__(self, sessions):
        self.sessions = sessions

    async def get(self, user_id: str) -> dict:
        async with self.sessions() as session:
            rows = (await session.execute(select(UserPreferenceRow).where(UserPreferenceRow.user_id == user_id))).scalars()
            return {row.key: row.value for row in rows}

    async def get_key(self, user_id: str, key: str) -> object:
        async with self.sessions() as session:
            return await session.scalar(select(UserPreferenceRow.value).where(UserPreferenceRow.user_id == user_id, UserPreferenceRow.key == key))

    async def reserve_key(self, user_id: str, key: str, value: dict) -> bool:
        """One durable creator across processes; never overwrite an existing hold."""
        async with self.sessions() as session, session.begin():
            insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            statement = insert(UserPreferenceRow).values(user_id=user_id, key=key, value=value).on_conflict_do_nothing(index_elements=["user_id", "key"]).returning(UserPreferenceRow.user_id)
            return (await session.scalar(statement)) is not None

    async def finish_reserved_key(self, user_id: str, key: str, nonce: str, value: dict) -> bool:
        return await self.transition_key(user_id, key, nonce, "creating", value)

    async def transition_key(self, user_id: str, key: str, nonce: str, state: str, value: dict) -> bool:
        """Atomic actor-key state/nonce fence, including across worker processes."""
        async with self.sessions() as session, session.begin():
            statement = (
                update(UserPreferenceRow)
                .where(
                    UserPreferenceRow.user_id == user_id,
                    UserPreferenceRow.key == key,
                    UserPreferenceRow.value["state"].as_string() == state,
                    UserPreferenceRow.value["nonce"].as_string() == nonce,
                )
                .values(value=value)
                .returning(UserPreferenceRow.user_id)
            )
            return (await session.scalar(statement)) is not None

    async def patch(self, user_id: str, values: dict) -> None:
        async with self.sessions() as session, session.begin():
            insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
            # Consistent key order also avoids opposite-order row-lock cycles.
            for key, value in sorted(values.items()):
                statement = insert(UserPreferenceRow).values(user_id=user_id, key=key, value=value)
                await session.execute(statement.on_conflict_do_update(index_elements=["user_id", "key"], set_={"value": statement.excluded.value}))
