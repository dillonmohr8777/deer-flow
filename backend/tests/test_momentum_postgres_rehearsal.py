"""Structural tests for the Postgres rehearsal/cutover deploy artifacts.

Pins the shape of deploy/momentum/compose.postgres.yaml and
workspace.config.postgres.yaml so a future edit cannot silently reintroduce
a published Postgres port, a hardcoded password, or let the two workspace
config files drift outside their one intentional difference (`database:`).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "deploy" / "momentum" / "compose.postgres.yaml"
BASE_CONFIG_PATH = REPO_ROOT / "deploy" / "momentum" / "workspace.config.yaml"
PG_CONFIG_PATH = REPO_ROOT / "deploy" / "momentum" / "workspace.config.postgres.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_postgres_service_publishes_no_port():
    postgres = _load(COMPOSE_PATH)["services"]["postgres"]
    assert "ports" not in postgres


def test_postgres_password_is_env_var_not_hardcoded():
    env = _load(COMPOSE_PATH)["services"]["postgres"]["environment"]
    password_entry = next(e for e in env if e.startswith("POSTGRES_PASSWORD="))
    assert password_entry == "POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env, never hardcoded}"


def test_gateway_database_url_points_at_postgres_service():
    env = _load(COMPOSE_PATH)["services"]["gateway"]["environment"]
    dsn_entry = next(e for e in env if e.startswith("DATABASE_URL="))
    assert dsn_entry.startswith("DATABASE_URL=postgresql://")
    assert "@postgres:5432/" in dsn_entry


def test_postgres_service_healthcheck_present():
    compose = _load(COMPOSE_PATH)
    assert "healthcheck" in compose["services"]["postgres"]
    assert compose["services"]["gateway"]["depends_on"]["postgres"]["condition"] == "service_healthy"


def test_postgres_config_uses_env_var_dsn():
    config = _load(PG_CONFIG_PATH)
    assert config["database"]["backend"] == "postgres"
    assert config["database"]["postgres_url"] == "$DATABASE_URL"


def test_postgres_config_matches_base_config_outside_database_block():
    base = _load(BASE_CONFIG_PATH)
    pg = _load(PG_CONFIG_PATH)
    assert base["database"]["backend"] == "sqlite"  # sanity: base file untouched

    base_without_db = {k: v for k, v in base.items() if k != "database"}
    pg_without_db = {k: v for k, v in pg.items() if k != "database"}
    assert base_without_db == pg_without_db
