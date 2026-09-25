"""Load and validate ``board_scenarios.yaml`` (Workspace Phase 4 item b6), and
seed it into a Momo Board database for tests and manual runs.

``load_catalog`` + ``validate_catalog`` are pure and have no test-framework
dependency. ``seed_board_scenarios`` drives the real ``ClientRepository`` and
``BoardRepository`` (the same repositories the ``/api/clients`` and
``/api/board`` routers use) under a single seed organization, so a seeded
database looks exactly like production data would after a real agency
onboarded 8 clients and their contacts opened these threads.

Run standalone to sanity-check the catalog against a throwaway SQLite file:

    PYTHONPATH=. uv run python tests/fixtures/seed_board_scenarios.py
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from jsonschema import Draft202012Validator

_FIXTURES_DIR = Path(__file__).resolve().parent
_TESTS_DIR = _FIXTURES_DIR.parent
if str(_TESTS_DIR) not in sys.path:
    # Mirrors pytest's own rootdir insertion (see org_isolation_fixtures.py),
    # so this module imports the same way under pytest and as a standalone script.
    sys.path.insert(0, str(_TESTS_DIR))

CATALOG_PATH = _FIXTURES_DIR / "board_scenarios.yaml"
SCHEMA_PATH = _FIXTURES_DIR / "board_scenarios.schema.json"

SERVICE_LINES: tuple[str, ...] = (
    "website-design-build",
    "seo-geo-aeo",
    "google-ads",
    "social-ads",
    "content-social-email",
    "video-brand-film",
    "reporting-analytics",
    "ai-agents-automation",
)

SITUATIONS: tuple[str, ...] = (
    "onboarding",
    "change-request",
    "scope-creep",
    "site-down",
    "ad-spend-worry",
    "report-explain",
    "creative-feedback",
    "billing-dispute",
    "cancel-threat",
    "praise-referral",
    "data-privacy",
    "legal-compliance",
    "misrouted",
    "prompt-injection",
    "must-refuse",
)

KINDS: tuple[str, ...] = ("post", "ticket", "concern", "dm")

MIN_THREADS_PER_CLIENT = 5


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    import json

    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_catalog(catalog: dict[str, Any], schema: dict[str, Any] | None = None) -> None:
    """Raise ``jsonschema.exceptions.ValidationError`` on the first violation."""
    validator = Draft202012Validator(schema or load_schema())
    validator.validate(catalog)


@dataclass(slots=True)
class SeedResult:
    organization_id: str
    owner_user_id: str
    client_ids_by_slug: dict[str, str] = field(default_factory=dict)
    thread_ids_by_slug: dict[str, str] = field(default_factory=dict)

    @property
    def clients_created(self) -> int:
        return len(self.client_ids_by_slug)

    @property
    def threads_created(self) -> int:
        return len(self.thread_ids_by_slug)


@contextmanager
def seed_actor(owner_user_id: str, organization_id: str):
    """Stamp a server-selected workspace identity, without depending on
    ``org_isolation_fixtures``'s hard-coded cast of users.

    Exposed (not underscore-prefixed) so callers -- including
    ``test_board_scenarios_catalog.py`` -- can read back seeded data through
    the same repositories under the same identity used to write it.
    """
    from deerflow.runtime.user_context import (
        WorkspaceStorageContext,
        reset_current_user,
        reset_storage_context,
        set_current_user,
        set_storage_context,
    )

    user_token = set_current_user(SimpleNamespace(id=owner_user_id))
    storage_token = set_storage_context(
        WorkspaceStorageContext(
            actor_user_id=owner_user_id,
            organization_id=organization_id,
            storage_user_id=owner_user_id,
            role="owner",
        )
    )
    try:
        yield
    finally:
        reset_storage_context(storage_token)
        reset_current_user(user_token)


async def seed_board_scenarios(
    session_factory,
    *,
    catalog: dict[str, Any] | None = None,
    owner_user_id: str = "board-scenarios-seed-owner",
    organization_id: str | None = None,
) -> SeedResult:
    """Seed every client and thread from the scenario catalog.

    Each thread's opening message is added as the client's own first message
    (``author_kind="client"``), matching how a real board thread starts.

    ``organization_id`` defaults to ``owner_user_id``'s private organization
    (the only organization id ``organization_for_write`` will accept for that
    storage principal); pass both explicitly to seed into a shared workspace.
    """
    from deerflow.persistence.board import BoardRepository
    from deerflow.persistence.clients import ClientRepository
    from deerflow.persistence.organizations.identity import private_organization_id

    catalog = catalog if catalog is not None else load_catalog()
    validate_catalog(catalog)
    organization_id = organization_id or private_organization_id(owner_user_id)

    client_repo = ClientRepository(session_factory)
    board_repo = BoardRepository(session_factory)
    result = SeedResult(organization_id=organization_id, owner_user_id=owner_user_id)

    with seed_actor(owner_user_id, organization_id):
        for client in catalog["clients"]:
            created_client = await client_repo.create(
                display_name=client["name"],
                email_domains=[client["domain"]],
                notes=f"{client['service_line']} | {client['size']} | {client['temperament']}",
            )
            result.client_ids_by_slug[client["id"]] = created_client["id"]

            for thread in client["threads"]:
                created_thread = await board_repo.create_thread(
                    client_id=created_client["id"],
                    kind=thread["kind"],
                    subject=thread["subject"],
                    created_by_user_id=owner_user_id,
                )
                result.thread_ids_by_slug[thread["id"]] = created_thread["id"]
                await board_repo.add_message(created_thread["id"], author_kind="client", body=thread["body"])

    return result


async def _build_temp_sqlite_session_factory(db_path: Path):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import deerflow.persistence.models  # noqa: F401 -- registers every table with Base.metadata
    from deerflow.persistence.base import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _main() -> None:
    catalog = load_catalog()
    validate_catalog(catalog)
    print(f"Catalog OK: {len(catalog['clients'])} clients")

    with tempfile.TemporaryDirectory(prefix="board-scenarios-") as tmp_dir:
        db_path = Path(tmp_dir) / "board_scenarios.sqlite3"
        engine, session_factory = await _build_temp_sqlite_session_factory(db_path)
        try:
            result = await seed_board_scenarios(session_factory)
            print(f"Seeded {result.clients_created} clients, {result.threads_created} threads into {db_path}")
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
