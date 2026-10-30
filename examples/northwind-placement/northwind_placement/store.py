"""Small workspace journal; transactions bind mutations to their retry receipts."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException


def now():
    return datetime.now(UTC)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, data_dir: Path, organization_id: str, workspace_id: str, user_id: str):
        scope = hashlib.sha256(encode([organization_id, workspace_id]).encode()).hexdigest()
        self.path = data_dir / f"{scope}.sqlite3"
        self.user_id = user_id

    @contextmanager
    def transaction(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.path, timeout=5)
        self.path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS records(kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(kind,id));
                CREATE TABLE IF NOT EXISTS retries(key TEXT PRIMARY KEY, digest TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS suppressed(kind TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(kind,value));
                CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY, at TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, entity_id TEXT NOT NULL);
            """)
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def mutate(self, key, action, payload, operation):
        digest = hashlib.sha256(encode([action, payload]).encode()).hexdigest()
        key = encode([self.user_id, key])
        with self.transaction() as connection:
            prior = connection.execute("SELECT digest,response FROM retries WHERE key=?", (key,)).fetchone()
            if prior:
                if prior["digest"] != digest:
                    raise HTTPException(409, "Idempotency-Key was already used for different input")
                return json.loads(prior["response"])
            result = operation(connection)
            connection.execute("INSERT INTO retries VALUES (?,?,?)", (key, digest, encode(result)))
            connection.execute("INSERT INTO audit(at,actor,action,entity_id) VALUES (?,?,?,?)", (now().isoformat(), self.user_id, action, result["id"]))
            return result


def records(connection, kind):
    return [json.loads(row[0]) for row in connection.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,))]


def get(connection, kind, record_id):
    row = connection.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, record_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Record not found")
    return json.loads(row[0])


def put(connection, kind, body):
    connection.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body", (kind, body["id"], encode(body)))
    return body
