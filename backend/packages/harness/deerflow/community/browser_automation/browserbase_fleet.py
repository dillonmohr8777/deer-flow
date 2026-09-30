"""Operator-configured, model-free Browserbase jobs with a private shared ledger.

No Gateway registration or scheduler activation happens on import. Model inputs
select a preapproved job, never URLs, credentials, clients, contexts or budgets.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard, cast
from uuid import uuid4

import httpx

from .browserbase_qa import BrowserbaseAPI, QaPolicy, capture_page, existing_api_key, playwright_available, run_qa


class FleetBlocked(ValueError):
    """A bounded admission failure safe to show without credential-bearing errors."""


def _number(value: Any) -> TypeGuard[float | int]:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0


def _reject_symlinks(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise FleetBlocked("Private paths cannot contain symlinks")


def _read_private_config(path: Path) -> dict:
    _reject_symlinks(path)
    if path.stat().st_mode & 0o077:
        raise FleetBlocked("Operator config must be private (0600)")
    return json.loads(path.read_text())


def _artifact(path: Path, filename: str, value: Any) -> None:
    _reject_symlinks(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_json(path / filename, value)


def _private_json(path: Path, value: Any) -> None:
    _reject_symlinks(path)
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        json.dump(value, handle, indent=2)


class UsageLedger:
    """One host-private SQLite file shared by every fleet worker (no app migration).

    Charged reservations stay charged for the entire attested billing cycle,
    even after release. Provider usage lag therefore cannot replenish credits.
    Ambiguous creates stay active and block the fleet until operator readback.
    """

    def __init__(self, path: Path):
        _reject_symlinks(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists() and path.stat().st_mode & 0o077:
            raise FleetBlocked("Ledger must be private (0600)")
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600) if not path.exists() else None
        if fd is not None:
            os.close(fd)
        self.path = path
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS cycle (id TEXT PRIMARY KEY, baseline REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS reservation (
                    id TEXT PRIMARY KEY, cycle TEXT NOT NULL, job TEXT NOT NULL,
                    minutes REAL NOT NULL, state TEXT NOT NULL, session TEXT,
                    occurrence TEXT NOT NULL UNIQUE, created REAL NOT NULL);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def reserve(self, job: str, occurrence: str, account: dict, observed: float, *, now: float | None = None, cadence: int = 0) -> str:
        now = time.time() if now is None else now
        # The attestation comes from an operator-owned private config, not an agent.
        if account.get("verified_included_only") is not True:
            raise FleetBlocked("Account-wide included allowance and overage stop are unverified")
        cycle = account.get("cycle_id")
        expiry = account.get("cycle_end_epoch")
        verified = account.get("verified_at_epoch")
        baseline = account.get("account_used_minutes")
        ceiling = account.get("ceiling_minutes", 50)
        included = account.get("included_minutes")
        if not isinstance(cycle, str) or not cycle or not all(_number(v) for v in (expiry, verified, baseline, ceiling, included, observed)):
            raise FleetBlocked("Unknown account usage or cycle; dispatch refused")
        expiry, verified, baseline, ceiling, included = (float(cast(float, value)) for value in (expiry, verified, baseline, ceiling, included))
        if now >= expiry or verified > now or now - verified > 86400 or ceiling <= 0 or ceiling > included:
            raise FleetBlocked("Expired account proof or unsafe ceiling; dispatch refused")
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM reservation WHERE state IN ('reserved','uncertain')").fetchone():
                raise FleetBlocked("Pending or ambiguous dispatch needs reconciliation")
            if db.execute("SELECT COUNT(*) FROM reservation WHERE state='running'").fetchone()[0] >= 2:
                raise FleetBlocked("Fleet concurrency ceiling reached")
            if cadence and db.execute("SELECT 1 FROM reservation WHERE job=? AND created>?", (job, now - cadence)).fetchone():
                raise FleetBlocked("Job cadence is not yet due")
            if db.execute("SELECT 1 FROM reservation WHERE occurrence=?", (occurrence,)).fetchone():
                raise FleetBlocked("Occurrence already reserved; no automatic retry")
            db.execute("INSERT OR IGNORE INTO cycle VALUES (?,?)", (cycle, baseline))
            original = db.execute("SELECT baseline FROM cycle WHERE id=?", (cycle,)).fetchone()[0]
            charged = db.execute("SELECT COALESCE(SUM(minutes),0) FROM reservation WHERE cycle=?", (cycle,)).fetchone()[0]
            # Two minutes covers one 60s provider timeout with rounding margin.
            if max(original, baseline, observed) + charged + 2 > ceiling:
                raise FleetBlocked("Included-usage protective ceiling reached")
            token = str(uuid4())
            db.execute("INSERT INTO reservation VALUES (?,?,?,?,?,?,?,?)", (token, cycle, job, 2, "reserved", None, occurrence, now))
            return token

    def running(self, token: str, session: str) -> None:
        with self.transaction() as db:
            changed = db.execute("UPDATE reservation SET state='running',session=? WHERE id=? AND state='reserved'", (session, token)).rowcount
            if changed != 1:
                raise FleetBlocked("Reservation ownership lost")

    def finish(self, token: str, terminal: bool) -> None:
        with self.transaction() as db:
            db.execute("UPDATE reservation SET state=? WHERE id=? AND state IN ('reserved','running')", ("finished" if terminal else "uncertain", token))

    def reconcile(self, token: str, session: str, status: str) -> None:
        # Call only after API readback of the exact known session; no timeout-based reclaim.
        if status not in {"COMPLETED", "ERROR", "TIMED_OUT"}:
            raise FleetBlocked("Session termination unconfirmed")
        with self.transaction() as db:
            changed = db.execute("UPDATE reservation SET state='finished' WHERE id=? AND session=? AND state IN ('uncertain','running')", (token, session)).rowcount
            if changed != 1:
                raise FleetBlocked("Exact session ownership is unconfirmed")

    def bind_owned_readback(self, token: str, session: str) -> None:
        with self.transaction() as db:
            changed = db.execute("UPDATE reservation SET session=? WHERE id=? AND session IS NULL AND state='uncertain'", (session, token)).rowcount
            if changed != 1:
                raise FleetBlocked("Ambiguous reservation is not available for ownership readback")

    def record_local(self, job: str, occurrence: str, cadence: int) -> None:
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM reservation WHERE job=? AND created>?", (job, time.time() - cadence)).fetchone():
                raise FleetBlocked("Job cadence is not yet due")
            if db.execute("SELECT 1 FROM reservation WHERE occurrence=?", (occurrence,)).fetchone():
                raise FleetBlocked("Occurrence already recorded")
            db.execute("INSERT INTO reservation VALUES (?,?,?,?,?,?,?,?)", (str(uuid4()), "local", job, 0, "local_attempt", None, occurrence, time.time()))

    def status(self) -> list[dict]:
        with self.transaction() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM reservation ORDER BY created")]


@dataclass(frozen=True)
class FleetJob:
    id: str
    client_id: str
    workflow: str
    url: str | None
    allowed_hosts: tuple[str, ...]
    interval_seconds: int
    draft_fields: dict | None = None


class Fleet:
    def __init__(self, config: dict, registry: dict, ledger: UsageLedger, output: Path):
        self.config = config
        self.ledger = ledger
        _reject_symlinks(output)
        self.output = output
        clients = {client["id"]: client for client in registry["clients"]}
        self.jobs: dict[str, FleetJob] = {}
        for raw in config.get("jobs", []):
            job = FleetJob(**{**raw, "allowed_hosts": tuple(raw.get("allowed_hosts", []))})
            if job.id in self.jobs or job.client_id not in clients or job.client_id == "align-hcm":
                raise FleetBlocked("Unknown, duplicate or historical client job")
            if job.workflow not in {"mobile_qa", "public_research", "report_retrieval", "local_draft"}:
                raise FleetBlocked("Workflow not admitted")
            if not isinstance(job.interval_seconds, int) or isinstance(job.interval_seconds, bool) or job.interval_seconds < 3600:
                raise FleetBlocked("Job cadence must be at least hourly")
            if not job.id.replace("-", "").isalnum() or not job.client_id.replace("-", "").isalnum():
                raise FleetBlocked("Job identifiers must be path-safe")
            if job.workflow in {"mobile_qa", "public_research"}:
                if not isinstance(job.url, str):
                    raise FleetBlocked("Public workflow needs an approved URL")
                QaPolicy(job.allowed_hosts).validate_url(job.url, target=True)
                approved = config.get("verified_client_hosts", {}).get(job.client_id, [])
                if not set(job.allowed_hosts).issubset(approved):
                    raise FleetBlocked("Exact hosts require operator provenance; email domains are not website proof")
            self.jobs[job.id] = job

    def due(self, now: float) -> list[str]:
        rows = self.ledger.status()
        return [job.id for job in self.jobs.values() if not any(row["job"] == job.id and now - row["created"] < job.interval_seconds for row in rows)]

    async def run(self, job_id: str, occurrence: str, api: BrowserbaseAPI | None, *, dry_run: bool = False, capture=None, report_reader=None) -> dict:
        if job_id not in self.jobs:
            raise FleetBlocked("Only operator-approved named jobs may run")
        job = self.jobs[job_id]
        summary = {"job": job.id, "client_id": job.client_id, "workflow": job.workflow, "model_calls": 0}
        if dry_run:
            return {**summary, "status": "dry_run", "cloud_dispatch": False, "scheduler_enabled": self.config.get("scheduler_enabled") is True}
        if job.workflow == "report_retrieval":
            # Private reports must go through the existing authenticated connector;
            # no unverified portal/context or generic credential transfer is admitted.
            if report_reader is None:
                return {**summary, "status": "blocked", "reason": "Exact authenticated report connector and client/account binding required"}
            await asyncio.to_thread(self.ledger.record_local, job.id, occurrence, job.interval_seconds)
            report = await report_reader(job.client_id, job.id)
            if not isinstance(report, dict) or report.get("client_id") != job.client_id or len(json.dumps(report)) > 1_000_000:
                raise FleetBlocked("Report client binding or size check failed")
            destination = self.output / job.client_id / str(uuid4())
            await asyncio.to_thread(_artifact, destination, "report.json", report)
            return {**summary, "status": "retrieved", "transport": "existing_authenticated_connector", "artifact": str(destination / "report.json"), "cloud_dispatch": False}
        if job.workflow == "local_draft":
            await asyncio.to_thread(self.ledger.record_local, job.id, occurrence, job.interval_seconds)
            destination = self.output / job.client_id / str(uuid4())
            await asyncio.to_thread(_artifact, destination, "draft.json", {"status": "draft_only", "client_id": job.client_id, "fields": job.draft_fields or {}, "submitted": False})
            return {**summary, "status": "draft_only", "artifact": str(destination / "draft.json"), "cloud_dispatch": False}
        if self.config.get("enabled") is not True or api is None:
            raise FleetBlocked("Fleet dispatch is disabled")
        if self.config.get("account", {}).get("project_id") != api.project_id:
            raise FleetBlocked("Account attestation is not bound to this provider project")
        usage = await api.usage()
        observed = usage.get("browserMinutes")
        if not _number(observed):
            raise FleetBlocked("Provider usage unavailable")
        if not isinstance(job.url, str):
            raise FleetBlocked("Public workflow needs an approved URL")
        observed = float(observed)
        if capture is None and not playwright_available():
            raise FleetBlocked("Playwright is not installed; no session created")
        destination = self.output / job.client_id / str(uuid4())
        # Validate filesystem before any spending-dependent admission.
        await asyncio.to_thread(_reject_symlinks, destination)
        token = await asyncio.to_thread(self.ledger.reserve, job.id, occurrence, self.config.get("account", {}), observed, cadence=job.interval_seconds)
        owner = self

        class ReservedAPI:
            project_id = api.project_id

            async def usage(self):
                return usage

            async def create(self, policy, *, reservation_id=None):
                created = await api.create(policy, reservation_id=token)
                await asyncio.to_thread(owner.ledger.running, token, created["id"])
                return created

            async def release(self, session_id):
                return await api.release(session_id)

            async def retrieve(self, session_id):
                return await api.retrieve(session_id)

        terminal = False
        try:
            policy = QaPolicy(job.allowed_hosts, max_reported_browser_minutes=float(self.config["account"].get("ceiling_minutes", 50)))
            result = await run_qa(ReservedAPI(), job.url, policy, destination, capture=capture or (research_capture if job.workflow == "public_research" else capture_page))
            terminal = result.get("release_status") in {"COMPLETED", "ERROR", "TIMED_OUT"}
            result.update(summary)
            result["reservation_id"] = token
            await asyncio.to_thread(_private_json, destination / "receipt.json", result)
            return result
        finally:
            # Includes cancellation/ambiguous HTTP create; never refund by guessing.
            await asyncio.to_thread(self.ledger.finish, token, terminal)


async def reconcile_owned_session(api: BrowserbaseAPI, ledger: UsageLedger, token: str, session_id: str) -> None:
    """Operator-only repair from exact provider readback; never infer from elapsed time."""
    session = await api.retrieve(session_id)
    metadata = session.get("userMetadata")
    if session.get("id") != session_id or session.get("projectId") != api.project_id or not isinstance(metadata, dict) or metadata.get("reservation_id") != token:
        raise FleetBlocked("Provider session ownership readback does not match reservation")
    status = session.get("status")
    if status not in {"COMPLETED", "ERROR", "TIMED_OUT"}:
        raise FleetBlocked("Owned session is not terminal; reservation retained")
    rows = await asyncio.to_thread(ledger.status)
    row = next((row for row in rows if row["id"] == token), None)
    if row is None:
        raise FleetBlocked("Unknown reservation")
    if row["session"] is None:
        await asyncio.to_thread(ledger.bind_owned_readback, token, session_id)
    await asyncio.to_thread(ledger.reconcile, token, session_id, status)


async def research_capture(connect_url: str, policy: QaPolicy, target: str, output: Path) -> list[dict]:
    # Reuse the stricter QA transport and screenshots as source evidence. DOM facts
    # are bounded metrics; evidence is not treated as instructions to the model.
    return await capture_page(connect_url, policy, target, output, extract_text=True)


async def _run_named_job_worker(config_path: Path, job_id: str, *, operator_id: str, dry_run: bool = False, report_reader=None) -> dict:
    config = await asyncio.to_thread(_read_private_config, config_path)
    if operator_id != config.get("operator_id"):
        raise FleetBlocked("Operator binding mismatch")
    registry = await asyncio.to_thread(lambda: json.loads(Path(config["registry_path"]).read_text()))
    ledger = await asyncio.to_thread(UsageLedger, Path(config["ledger_path"]))
    fleet = await asyncio.to_thread(Fleet, config, registry, ledger, Path(config["output_path"]))
    if job_id not in fleet.jobs:
        raise FleetBlocked("Only operator-approved named jobs may run")
    if dry_run or fleet.jobs[job_id].workflow in {"local_draft", "report_retrieval"}:
        return await asyncio.to_thread(lambda: asyncio.run(fleet.run(job_id, str(uuid4()), None, dry_run=dry_run, report_reader=report_reader)))
    key = await asyncio.to_thread(existing_api_key)
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as http:
        # Fleet uses a worker loop so its shared SQLite lock never blocks Gateway IO.
        api = BrowserbaseAPI(key, config["project_id"], http)
        return await fleet.run(job_id, str(uuid4()), api)


async def _scheduler_tick_worker(config_path: Path, *, dry_run: bool = True) -> list[dict]:
    config = await asyncio.to_thread(_read_private_config, config_path)
    if not dry_run and config.get("scheduler_enabled") is not True:
        raise FleetBlocked("Scheduler is disabled until runtime/account review")
    registry = await asyncio.to_thread(lambda: json.loads(Path(config["registry_path"]).read_text()))
    ledger = await asyncio.to_thread(UsageLedger, Path(config["ledger_path"]))
    fleet = await asyncio.to_thread(Fleet, config, registry, ledger, Path(config["output_path"]))
    results = []
    # Sequential initial scheduling intentionally leaves the second slot for staff.
    for job_id in await asyncio.to_thread(fleet.due, time.time()):
        try:
            results.append(await run_named_job(config_path, job_id, operator_id=config["operator_id"], dry_run=dry_run))
        except FleetBlocked as exc:
            results.append({"job": job_id, "status": "blocked", "reason": str(exc)})
    return results


async def run_named_job(config_path: Path, job_id: str, *, operator_id: str, dry_run: bool = False, report_reader=None) -> dict:
    # The complete browser+SQLite lifecycle belongs to one dedicated worker loop.
    return await asyncio.to_thread(lambda: asyncio.run(_run_named_job_worker(config_path, job_id, operator_id=operator_id, dry_run=dry_run, report_reader=report_reader)))


async def scheduler_tick(config_path: Path, *, dry_run: bool = True) -> list[dict]:
    return await asyncio.to_thread(lambda: asyncio.run(_scheduler_tick_worker(config_path, dry_run=dry_run)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(asyncio.run(scheduler_tick(args.config, dry_run=args.dry_run))))
    except Exception as exc:
        print(json.dumps({"status": "blocked", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
