"""Momo Board scenario catalog (Workspace Phase 4 item b6).

Three things this file proves, per ``docs/momo-week/QUEUE.md``'s acceptance
bar for b6:

1. ``board_scenarios.yaml`` validates against ``board_scenarios.schema.json``.
2. The catalog's seed script loads every client and thread into a temp
   SQLite database, and what lands there matches the catalog exactly.
3. Count checks prove the required coverage: one client per Momentum service
   line, at least 5 threads per client, every thread ``kind`` represented,
   and every required ``situation`` represented at least once.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest
import pytest_asyncio
from fixtures.seed_board_scenarios import (
    KINDS,
    MIN_THREADS_PER_CLIENT,
    SERVICE_LINES,
    SITUATIONS,
    load_catalog,
    load_schema,
    seed_actor,
    seed_board_scenarios,
    validate_catalog,
)
from jsonschema.exceptions import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401 -- registers every table with Base.metadata
from deerflow.persistence.base import Base
from deerflow.persistence.board import BoardRepository
from deerflow.persistence.clients import ClientRepository


@pytest.fixture()
def catalog() -> dict:
    return load_catalog()


@pytest.fixture()
def schema() -> dict:
    return load_schema()


@pytest_asyncio.fixture()
async def seeded_session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def test_catalog_validates_against_schema(catalog, schema):
    validate_catalog(catalog, schema)


def test_catalog_rejects_a_bad_shape(schema):
    with pytest.raises(ValidationError):
        validate_catalog({"clients": [{"id": "x"}]}, schema)


def test_eight_clients_one_per_service_line(catalog):
    clients = catalog["clients"]
    assert len(clients) == 8

    service_lines = [c["service_line"] for c in clients]
    assert Counter(service_lines) == Counter(SERVICE_LINES), "every Momentum service line must appear exactly once"


def test_client_ids_and_domains_are_unique_and_invented(catalog):
    clients = catalog["clients"]
    ids = [c["id"] for c in clients]
    domains = [c["domain"] for c in clients]
    assert len(ids) == len(set(ids)), "duplicate client id"
    assert len(domains) == len(set(domains)), "duplicate client domain"
    for domain in domains:
        assert domain.endswith(".example"), f"{domain!r} is not a reserved .example domain"


def test_client_sizes_and_temperaments_are_mixed(catalog):
    clients = catalog["clients"]
    sizes = {c["size"] for c in clients}
    temperaments = {c["temperament"] for c in clients}
    assert sizes == {"solo", "small", "medium", "franchise"}
    assert temperaments == {"calm", "anxious", "terse", "angry"}


def test_every_client_has_at_least_five_threads(catalog):
    for client in catalog["clients"]:
        assert len(client["threads"]) >= MIN_THREADS_PER_CLIENT, f"{client['id']} has fewer than {MIN_THREADS_PER_CLIENT} threads"


def test_every_thread_kind_is_represented(catalog):
    observed = {thread["kind"] for client in catalog["clients"] for thread in client["threads"]}
    assert observed == set(KINDS)


def test_every_required_situation_is_represented(catalog):
    observed = {thread["situation"] for client in catalog["clients"] for thread in client["threads"]}
    missing = set(SITUATIONS) - observed
    assert not missing, f"situations missing from the catalog: {sorted(missing)}"


def test_thread_ids_are_globally_unique(catalog):
    thread_ids = [thread["id"] for client in catalog["clients"] for thread in client["threads"]]
    assert len(thread_ids) == len(set(thread_ids))


def test_must_refuse_and_injection_scenarios_never_expect_a_bare_draft(catalog):
    """The two hardest situations must always resolve to escalate, never a
    reply Momo could send unsupervised."""
    for client in catalog["clients"]:
        for thread in client["threads"]:
            if thread["situation"] in ("must-refuse", "prompt-injection"):
                assert thread["expected"]["action"] == "escalate", f"{thread['id']} must escalate, not draft"


def test_injection_and_misrouted_threads_forbid_other_clients_data(catalog):
    """Threads that try to pull another client's data must name at least one
    forbidden phrase, so a leaking draft has something concrete to fail on."""
    for client in catalog["clients"]:
        for thread in client["threads"]:
            if thread["situation"] in ("prompt-injection", "misrouted"):
                assert thread["expected"]["forbidden_phrases"], f"{thread['id']} needs forbidden_phrases naming what must not leak"


_PHONE_RE = re.compile(r"\b(\d{3})[-.](\d{3})[-.](\d{4})\b")


def test_any_phone_numbers_in_prose_use_the_reserved_555_01xx_range(catalog):
    for client in catalog["clients"]:
        for thread in client["threads"]:
            text = f"{thread['subject']} {thread['body']}"
            for match in _PHONE_RE.finditer(text):
                exchange, line = match.group(2), match.group(3)
                assert exchange == "555" and line.startswith("01"), f"{thread['id']} has a non-reserved phone number: {match.group(0)}"


@pytest.mark.asyncio
async def test_seed_loads_every_client_and_thread_into_a_temp_database(seeded_session_factory, catalog):
    result = await seed_board_scenarios(seeded_session_factory, catalog=catalog)

    expected_thread_count = sum(len(c["threads"]) for c in catalog["clients"])
    assert result.clients_created == len(catalog["clients"])
    assert result.threads_created == expected_thread_count

    client_repo = ClientRepository(seeded_session_factory)
    board_repo = BoardRepository(seeded_session_factory)

    with seed_actor(result.owner_user_id, result.organization_id):
        for client in catalog["clients"]:
            db_client_id = result.client_ids_by_slug[client["id"]]
            stored_client = await client_repo.get(db_client_id)
            assert stored_client is not None
            assert stored_client["display_name"] == client["name"]
            assert stored_client["email_domains"] == [client["domain"]]

            db_threads = await board_repo.list_threads(client_id=db_client_id)
            assert len(db_threads) == len(client["threads"])

            catalog_bodies = {thread["body"].strip() for thread in client["threads"]}
            for db_thread in db_threads:
                messages = await board_repo.list_messages(db_thread["id"])
                assert messages, f"seeded thread {db_thread['id']} has no opening message"
                assert messages[0]["body"].strip() in catalog_bodies
                assert messages[0]["author_kind"] == "client"
