"""One nullable compatibility column, without changing the rollback-known stamp.

This is the reviewed run-limit exception to the ordinary Alembic revision rule.
Accepted rollback images reject any newer revision but safely ignore this column.
Call only after successful ordinary bootstrap and while its lock is still owned,
or from the offline SQLite-to-Postgres migration script after its Alembic upgrade.
"""

from sqlalchemy import JSON, Connection, inspect, text


def ensure_run_limits_column(connection: Connection) -> None:
    """Add only private run timing; reject incompatible pre-existing shapes."""
    columns = {column["name"]: column for column in inspect(connection).get_columns("runs")}
    if "run_limits_json" not in columns:
        connection.execute(text("ALTER TABLE runs ADD COLUMN run_limits_json JSON"))
        columns = {column["name"]: column for column in inspect(connection).get_columns("runs")}
    column = columns["run_limits_json"]
    if not isinstance(column["type"], JSON) or column["nullable"] is not True or column["default"] is not None:
        raise RuntimeError("runs.run_limits_json must be nullable JSON without a server default; refusing schema drift")
