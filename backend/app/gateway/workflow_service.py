"""Owner-scoped workflow admissions using the app's native runtime and checkpoints.

The private ledger stores recipe inputs, paid-attempt receipts and artifact hashes;
it is not a client registry. Provider attempts are reserved atomically, never
retried after an uncertain outcome, and remain charged across restart/resume.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, overload

from deerflow.runtime.runs.manager import RunStartOutcome
from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus
from deerflow.runtime.user_context import WorkspaceStorageContext, reset_current_user, reset_storage_context, set_current_user, set_storage_context

FRAMEWORKS = ("langgraph", "crewai", "mastra", "deepagents", "agno", "agentkit")
TERMINAL = ("completed", "failed", "cancelled")
LIMITS = {
    "max_running": 3,
    "max_queued": 100,
    "max_model_calls_per_run": 6,
    "max_model_calls_per_day": 240,
    "max_output_tokens_per_run": 8192,
    "max_input_tokens_per_run": 60000,
    "max_browser_sessions_per_owner": 1,
}
MAX_ARTIFACT = 256 * 1024

# Persisted JSON payloads are validated by each admission/receipt boundary;
# operation overloads preserve the distinct SQLite result shapes for callers.
type Record = dict[str, Any]
type StorageResult = Record | list[Record] | tuple[Record, bool] | None


@dataclass
class _NativeStorageUser:
    id: str


class WorkflowServiceError(Exception):
    def __init__(self, code: str, status_code: int = 400):
        self.code, self.status_code = code, status_code
        super().__init__(code)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _public(data: dict) -> dict:
    result = {key: value for key, value in data.items() if not key.startswith("_")}
    if isinstance(result.get("usage"), dict):
        result["usage"] = {**result["usage"]}
        result["usage"]["complete"] = result["usage"].get("unknown_model_calls", 0) == 0
    return result


def _definition_dict(definition) -> dict:
    return definition.model_dump() if hasattr(definition, "model_dump") else dict(definition)


def _native_storage_user(data: dict) -> str:
    """Private native bucket; shared workspace APIs cannot authorize this owner."""
    return "wf_" + hashlib.sha256(("momo-workflow-native\0" + data["_scope"]).encode()).hexdigest()[:60]


@contextmanager
def _native_context(data: dict):
    """Quarantine only native bookkeeping; real authority uses the original owner."""
    native_user = _native_storage_user(data)
    user_token = set_current_user(_NativeStorageUser(native_user))
    storage_token = set_storage_context(WorkspaceStorageContext(data["_actor"], None, native_user))
    try:
        yield
    finally:
        reset_storage_context(storage_token)
        reset_current_user(user_token)


class WorkflowService:
    def __init__(self, path: Path, *, checkpointer, adapter, browser_service=None, run_manager=None, thread_store=None, event_store=None, authority=None, engine=None):
        self.path = Path(path)
        self.artifact_dir = self.path.parent / "workflow-artifacts"
        self.checkpointer, self.adapter, self.browser_service = checkpointer, adapter, browser_service
        self.run_manager, self.thread_store, self.authority, self.engine = run_manager, thread_store, authority, engine
        self.event_store = event_store
        self.limits = dict(LIMITS)
        self.tasks: dict[str, asyncio.Task] = {}
        self.pump_task: asyncio.Task | None = None
        self.lease = None
        self.started = self.closing = False
        self.lock, self.browser_lock = asyncio.Lock(), asyncio.Lock()
        self.journal_lock = asyncio.Lock()

    @staticmethod
    def enabled() -> bool:
        return os.environ.get("MOMOBOT_WORKFLOWS_ENABLED", "").lower() in ("1", "true", "yes")

    def _init(self):
        import fcntl

        for target in (self.path, self.path.with_suffix(".lock"), self.artifact_dir, *self.path.parents):
            if target.is_symlink():
                raise WorkflowServiceError("unsafe_state_path", 503)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifact_dir.mkdir(exist_ok=True, mode=0o700)
        os.chmod(self.artifact_dir, 0o700)
        lease = self.path.with_suffix(".lock").open("a+b")
        os.chmod(self.path.with_suffix(".lock"), 0o600)
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lease.close()
            raise WorkflowServiceError("service_already_running", 503) from None
        self.lease = lease
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS workflow_jobs (id TEXT PRIMARY KEY, scope TEXT NOT NULL, idem TEXT NOT NULL, fingerprint TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, data TEXT NOT NULL, UNIQUE(scope,idem))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS workflow_attempts (run_id TEXT NOT NULL, call_id TEXT NOT NULL, fingerprint TEXT NOT NULL, "
                "state TEXT NOT NULL, created REAL NOT NULL, reserved_output INTEGER NOT NULL, result TEXT, PRIMARY KEY(run_id,call_id))"
            )
            if "reserved_input" not in {row[1] for row in db.execute("PRAGMA table_info(workflow_attempts)")}:
                db.execute("ALTER TABLE workflow_attempts ADD COLUMN reserved_input INTEGER NOT NULL DEFAULT 0")
            db.execute("CREATE TABLE IF NOT EXISTS workflow_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, created REAL NOT NULL, event TEXT NOT NULL)")
            for row in db.execute("SELECT data FROM workflow_jobs"):
                data = json.loads(row[0])
                if (data.get("native_run_id") or data.get("thread_id")) and data.get("_native_storage_user") != _native_storage_user(data):
                    raise RuntimeError("workflow_native_namespace_migration_required")
        os.chmod(self.path, 0o600)

    @staticmethod
    def _load(db, run_id: str, owner: str) -> dict:
        row = db.execute("SELECT data FROM workflow_jobs WHERE id=? AND scope=?", (run_id, owner)).fetchone()
        if row is None:
            raise WorkflowServiceError("not_found", 404)
        return json.loads(row[0])

    @staticmethod
    def _save(db, data: dict):
        data["updated_at"] = _now()
        db.execute("UPDATE workflow_jobs SET status=?,data=? WHERE id=? AND scope=?", (data["status"], _json(data), data["id"], data["_scope"]))

    def _db(self, action: str, *args: Any) -> StorageResult:
        with sqlite3.connect(self.path, timeout=15) as db:
            if action == "get":
                return self._load(db, *args)
            if action == "list":
                return [json.loads(row[0]) for row in db.execute("SELECT data FROM workflow_jobs WHERE scope=? ORDER BY created DESC LIMIT 100", args)]
            if action == "counts":
                return dict(db.execute("SELECT status,count(*) FROM workflow_jobs WHERE scope=? GROUP BY status", args))
            db.execute("BEGIN IMMEDIATE")
            if action == "admit":
                data, key, fingerprint, limits = args
                row = db.execute("SELECT fingerprint,data FROM workflow_jobs WHERE scope=? AND idem=?", (data["_scope"], key)).fetchone()
                if row:
                    if row[0] != fingerprint:
                        raise WorkflowServiceError("idempotency_conflict", 409)
                    return json.loads(row[1]), False
                count = db.execute("SELECT count(*) FROM workflow_jobs WHERE status IN ('queued','running')").fetchone()[0]
                if count >= limits["max_queued"] + limits["max_running"]:
                    raise WorkflowServiceError("queue_full", 429)
                db.execute("INSERT INTO workflow_jobs VALUES (?,?,?,?,?,?,?)", (data["id"], data["_scope"], key, fingerprint, data["status"], time.time(), _json(data)))
                return data, True
            if action == "claim":
                limits = args[0]
                count = db.execute("SELECT count(*) FROM workflow_jobs WHERE status='running'").fetchone()[0]
                if count >= limits["max_running"]:
                    return None
                row = db.execute("SELECT data FROM workflow_jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                if row is None:
                    return None
                data = json.loads(row[0])
                data["status"] = "running"
                self._save(db, data)
                return data
            if action == "recover":
                for row in db.execute("SELECT data FROM workflow_jobs WHERE status='running'").fetchall():
                    data = json.loads(row[0])
                    data["status"], data["error"] = "interrupted", "interrupted_by_restart"
                    self._save(db, data)
                return
            if action == "patch":
                run_id, owner, values = args
                data = self._load(db, run_id, owner)
                data.update(values)
                self._save(db, data)
                return data
            if action == "terminal":
                run_id, owner, values = args
                data = self._load(db, run_id, owner)
                if data["status"] != "running":
                    return data
                data.update(values)
                self._save(db, data)
                return data
            if action == "cancel":
                data = self._load(db, *args)
                if data["status"] in TERMINAL:
                    return data, False
                data.update(status="cancelled", accepted=False, error="cancelled")
                self._save(db, data)
                return data, True
            if action == "event":
                run_id, owner, event = args
                data = self._load(db, run_id, owner)
                if data["status"] != "running":
                    raise WorkflowServiceError("run_not_running", 409)
                db.execute("INSERT INTO workflow_events(run_id,created,event) VALUES(?,?,?)", (run_id, time.time(), _json(event)))
                steps = [step for step in data["steps"] if step["name"] != event["name"]]
                data["steps"] = (steps + [event])[-25:]
                self._save(db, data)
                return
            if action == "resume":
                run_id, owner = args
                data = self._load(db, run_id, owner)
                if data["status"] != "interrupted":
                    raise WorkflowServiceError("run_not_interrupted", 409)
                if db.execute("SELECT 1 FROM workflow_attempts WHERE run_id=? AND state='reserved' LIMIT 1", (run_id,)).fetchone():
                    raise WorkflowServiceError("uncertain_provider_attempt", 409)
                if data.get("_resumes", 0) >= 3:
                    raise WorkflowServiceError("resume_limit", 429)
                if db.execute("SELECT count(*) FROM workflow_jobs WHERE status IN ('queued','running')").fetchone()[0] >= self.limits["max_queued"] + self.limits["max_running"]:
                    raise WorkflowServiceError("queue_full", 429)
                data.update(status="queued", error=None, _resume=True, _resumes=data.get("_resumes", 0) + 1)
                self._save(db, data)
                return data
            if action == "reserve_call":
                run_id, owner, call_id, fingerprint, reserve, limits, *input_bound = args
                data = self._load(db, run_id, owner)
                old = db.execute("SELECT fingerprint,state,result FROM workflow_attempts WHERE run_id=? AND call_id=?", (run_id, call_id)).fetchone()
                if old:
                    if old[0] != fingerprint:
                        raise WorkflowServiceError("call_id_conflict", 409)
                    if old[1] != "complete":
                        raise WorkflowServiceError("uncertain_provider_attempt", 409)
                    return json.loads(old[2])
                if data["status"] != "running":
                    raise WorkflowServiceError("run_not_running", 409)
                if data["usage"]["model_calls"] >= limits["max_model_calls_per_run"]:
                    raise WorkflowServiceError("run_model_budget_exhausted", 429)
                daily = db.execute("SELECT count(*) FROM workflow_attempts WHERE created>?", (time.time() - 86400,)).fetchone()[0]
                if daily >= limits["max_model_calls_per_day"]:
                    raise WorkflowServiceError("daily_model_budget_exhausted", 429)
                held = db.execute("SELECT coalesce(sum(reserved_output),0) FROM workflow_attempts WHERE run_id=? AND state='reserved'", (run_id,)).fetchone()[0]
                held_input = db.execute("SELECT coalesce(sum(reserved_input),0) FROM workflow_attempts WHERE run_id=? AND state='reserved'", (run_id,)).fetchone()[0]
                reserve_input = input_bound[0] if input_bound else 0
                if (
                    reserve < 128
                    or reserve_input < 0
                    or data["usage"]["output_tokens"] + held + reserve > limits["max_output_tokens_per_run"]
                    or data["usage"]["input_tokens"] + held_input + reserve_input > limits["max_input_tokens_per_run"]
                    or data["usage"]["input_tokens"] >= limits["max_input_tokens_per_run"]
                ):
                    raise WorkflowServiceError("run_token_budget_exhausted", 429)
                db.execute("INSERT INTO workflow_attempts(run_id,call_id,fingerprint,state,created,reserved_output,reserved_input) VALUES(?,?,?,?,?,?,?)", (run_id, call_id, fingerprint, "reserved", time.time(), reserve, reserve_input))
                data["usage"]["model_calls"] += 1
                data["usage"]["unknown_model_calls"] = data["usage"].get("unknown_model_calls", 0) + 1
                self._save(db, data)
                return None
            if action == "finish_call":
                run_id, owner, call_id, result = args
                data = self._load(db, run_id, owner)
                updated = db.execute("UPDATE workflow_attempts SET state='complete',result=? WHERE run_id=? AND call_id=? AND state='reserved'", (_json(result), run_id, call_id))
                if updated.rowcount != 1:
                    raise WorkflowServiceError("attempt_state_conflict", 409)
                data["usage"]["input_tokens"] += result["usage"]["input_tokens"]
                data["usage"]["output_tokens"] += result["usage"]["output_tokens"]
                data["usage"]["unknown_model_calls"] = max(0, data["usage"].get("unknown_model_calls", 1) - 1)
                costs = [json.loads(row[0])["usage"].get("cost") for row in db.execute("SELECT result FROM workflow_attempts WHERE run_id=? AND state='complete'", (run_id,))]
                data["usage"]["cost"] = sum(costs) if costs and all(isinstance(cost, (int, float)) and not isinstance(cost, bool) for cost in costs) else None
                self._save(db, data)
                return data
        raise ValueError("Unknown workflow storage operation")

    @overload
    async def _storage(self, action: Literal["get", "patch", "terminal", "resume", "finish_call"], *args: Any) -> Record: ...

    @overload
    async def _storage(self, action: Literal["list"], *args: Any) -> list[Record]: ...

    @overload
    async def _storage(self, action: Literal["counts"], *args: Any) -> dict[str, int]: ...

    @overload
    async def _storage(self, action: Literal["admit", "cancel"], *args: Any) -> tuple[Record, bool]: ...

    @overload
    async def _storage(self, action: Literal["claim", "reserve_call"], *args: Any) -> Record | None: ...

    @overload
    async def _storage(self, action: Literal["recover", "event"], *args: Any) -> None: ...

    async def _storage(self, action: str, *args: Any) -> StorageResult:
        if not self.started:
            raise WorkflowServiceError("not_enabled" if not self.enabled() else "service_unavailable", 503)
        task = asyncio.create_task(asyncio.to_thread(self._db, action, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def start(self):
        if not self.enabled():
            return
        async with self.lock:
            if self.started:
                return
            try:
                initialization = asyncio.create_task(asyncio.to_thread(self._init))
                try:
                    await asyncio.shield(initialization)
                except asyncio.CancelledError:
                    await initialization
                    raise
                self.started = True
                await self._storage("recover")
                if self.engine is None:
                    from deerflow.workflows.engine import WorkflowEngine

                    self.engine = WorkflowEngine(self.checkpointer)
                self._wake()
            except BaseException:
                if self.lease is not None:
                    await asyncio.to_thread(self.lease.close)
                    self.lease = None
                self.started = False
                raise

    def _wake(self):
        if self.closing or self.pump_task is not None and not self.pump_task.done():
            return
        self.pump_task = asyncio.create_task(self._pump(), name="workflow-admission-pump")

    async def _pump(self):
        while not self.closing:
            data = await self._storage("claim", self.limits)
            if data is None:
                return
            task = asyncio.create_task(self._run(data), name=f"workflow-{data['id']}")
            self.tasks[data["id"]] = task
            task.add_done_callback(lambda done, run_id=data["id"]: self._done(run_id, done))

    def _done(self, run_id, task):
        self.tasks.pop(run_id, None)
        if not task.cancelled():
            task.exception()
        self._wake()

    async def capabilities(self):
        values = await asyncio.to_thread(self.adapter.capabilities)
        result = {name: values.get(name, {"available": False, "detail": "Adapter is not installed"}) for name in (*FRAMEWORKS, "stagehand")}
        result["browser"] = {"available": self.browser_service is not None and self.browser_service.started and bool(os.environ.get("BROWSERBASE_API_KEY")), "detail": "Public source capture; quota checked on admission"}
        installed = result["stagehand"]["available"]
        extension = os.environ.get("MOMOBOT_STAGEHAND_EXTENSION_ID", "")
        configured = bool(re.fullmatch(r"[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}", extension))
        result["stagehand"]["available"] = bool(installed and configured and result["browser"]["available"] and result["langgraph"]["available"])
        if installed and not configured:
            result["stagehand"]["detail"] = "installed_v4; stagehand_extension_not_configured"
        elif installed and not result["stagehand"]["available"]:
            result["stagehand"]["detail"] = "installed_v4; browser_or_model_not_configured"
        return result

    async def status(self, owner: str):
        counts = await self._storage("counts", owner) if self.started else {}
        return {"enabled": self.started and not self.closing, "frameworks": await self.capabilities(), "limits": self.limits, "running": counts.get("running", 0), "queued": counts.get("queued", 0)}

    async def create(self, owner: str, workflow_id: str, inputs: dict, framework: str, idempotency_key: str, *, actor: str, organization: str | None, storage_user: str):
        from deerflow.workflows.catalog import get_workflow, validate_inputs

        if not self.started or self.closing:
            raise WorkflowServiceError("not_enabled", 503)
        if framework not in FRAMEWORKS or not (await self.capabilities())[framework]["available"]:
            raise WorkflowServiceError("framework_unavailable", 503)
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key.strip()) <= 128:
            raise WorkflowServiceError("invalid_idempotency_key")
        try:
            definition = get_workflow(workflow_id)
            validate_inputs(definition, inputs)
            encoded = _json(inputs)
            if len(encoded.encode()) > 64 * 1024:
                raise ValueError("bounded inputs required")
        except (KeyError, ValueError, TypeError):
            raise WorkflowServiceError("input_invalid", 422) from None
        definition_data = _definition_dict(definition)
        fingerprint = hashlib.sha256(_json([workflow_id, inputs, framework]).encode()).hexdigest()
        now = _now()
        data = {
            "id": str(uuid.uuid4()),
            "workflow_id": workflow_id,
            "title": definition_data["title"],
            "framework": framework,
            "status": "queued",
            "accepted": False,
            "created_at": now,
            "updated_at": now,
            "steps": [],
            "output": None,
            "evidence": [],
            "usage": {"model_calls": 0, "input_tokens": 0, "output_tokens": 0, "cost": None},
            "error": None,
            "artifact": None,
            "_scope": owner,
            "_inputs": inputs,
            "_actor": actor,
            "_organization": organization,
            "_storage_user": storage_user,
            "_native_storage_user": _native_storage_user({"_scope": owner}),
            "_definition_hash": hashlib.sha256(_json(definition_data).encode()).hexdigest(),
            "_resume": False,
            "_resumes": 0,
        }
        data, _created = await self._storage("admit", data, idempotency_key, fingerprint, self.limits)
        self._wake()
        return _public(data)

    async def snapshot(self, owner: str, run_id: str):
        return _public(await self._storage("get", run_id, owner))

    async def list_runs(self, owner: str):
        return [_public(data) for data in await self._storage("list", owner)]

    async def _authorize(self, data):
        if self.authority is not None and not await self.authority(data["_actor"], data["_organization"], data["_storage_user"]):
            raise WorkflowServiceError("owner_authorization_changed", 403)

    async def _model(self, data: dict, **kwargs):
        await self._authorize(data)
        if self.closing:
            raise asyncio.CancelledError
        if kwargs.get("model") != "gpt-6.1-sol" or kwargs.get("effort") not in ("low", "medium", "high"):
            raise WorkflowServiceError("model_policy_denied", 403)
        if len(_json(kwargs).encode()) > 160 * 1024:
            raise WorkflowServiceError("model_context_too_large", 413)
        call_id = kwargs.get("call_id")
        if not isinstance(call_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id):
            raise WorkflowServiceError("invalid_call_id")
        latest = await self._storage("get", data["id"], data["_scope"])
        remaining = self.limits["max_output_tokens_per_run"] - latest["usage"]["output_tokens"]
        # High-effort reasoning shares the provider's output ceiling with the
        # artifact itself. Keep the same overall run budget while allowing a
        # single producer enough room to complete its bounded structured draft.
        per_call = 4096 if kwargs["effort"] == "high" else 2048
        reserve = min(per_call, max(0, remaining))
        reserve_input = max(0, self.limits["max_input_tokens_per_run"] - latest["usage"]["input_tokens"])
        fingerprint = hashlib.sha256(_json(kwargs).encode()).hexdigest()
        # Reserve all remaining input headroom. The adapter checks its actual
        # framework-generated request against this bound before provider dispatch.
        # Completed receipts release the difference; uncertain attempts retain it.
        if reserve_input < 2048 and latest["usage"]["model_calls"] == 0:
            raise WorkflowServiceError("run_token_budget_exhausted", 429)
        previous = await self._storage("reserve_call", data["id"], data["_scope"], call_id, fingerprint, reserve, self.limits, reserve_input)
        if previous is not None:
            await self._journal_model(latest, previous, kwargs)
            if previous.get("error"):
                raise WorkflowServiceError(previous["error"], 502)
            return previous
        try:
            result = await self.adapter.call(**kwargs, framework=data["framework"], max_output_tokens=reserve, input_token_limit=reserve_input)
        except Exception as error:
            usage = getattr(error, "usage", None)
            code = getattr(error, "code", "provider_request_failed")
            if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", code):
                code = "provider_request_failed"
            if isinstance(usage, dict) and all(type(usage.get(key)) is int and usage[key] >= 0 for key in ("input_tokens", "output_tokens")):
                failed = {
                    "output": {},
                    "model": kwargs["model"],
                    "effort": kwargs["effort"],
                    "usage": {**usage, "cost": None},
                    "error": code,
                    "_journal_context": {"run_id": latest.get("native_run_id"), "thread_id": latest.get("thread_id")},
                }
                stored = await self._storage("finish_call", data["id"], data["_scope"], call_id, failed)
                await self._journal_model(stored, failed, kwargs)
            raise WorkflowServiceError(code, 502) from None
        try:
            usage = result["usage"]
            if result["model"] != kwargs["model"] or result["effort"] != kwargs["effort"]:
                raise ValueError
            if any(isinstance(usage[key], bool) or not isinstance(usage[key], int) or usage[key] < 0 for key in ("input_tokens", "output_tokens")):
                raise ValueError
            if not isinstance(result["output"], dict) or len(_json(result).encode()) > MAX_ARTIFACT:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise WorkflowServiceError("provider_receipt_invalid", 502) from None
        result["_journal_context"] = {"run_id": latest.get("native_run_id"), "thread_id": latest.get("thread_id")}
        stored = await self._storage("finish_call", data["id"], data["_scope"], call_id, result)
        await self._journal_model(stored, result, kwargs)
        if stored["usage"]["output_tokens"] > self.limits["max_output_tokens_per_run"] or stored["usage"]["input_tokens"] > self.limits["max_input_tokens_per_run"]:
            raise WorkflowServiceError("provider_token_limit_exceeded", 429)
        return result

    async def _browser(self, data: dict, urls: list[str]):
        if self.browser_service is None:
            raise WorkflowServiceError("browser_unavailable", 503)
        await self._authorize(data)
        async with self.browser_lock:
            options = {}
            extension = os.environ.get("MOMOBOT_STAGEHAND_EXTENSION_ID", "")
            if extension:
                from app.gateway.workflow_adapters import browser_runner

                async def runner(connect_url, pages, *, session_id):
                    return await browser_runner(connect_url, pages, session_id=session_id, model_call=lambda **kwargs: self._model(data, **kwargs))

                options = {"browser_runner": runner, "extension_id": extension}
                await self._event(data, "stagehand", "running", worker_id="browser_researcher", model="gpt-6.1-sol", effort="low", detail="Extracting public snapshot evidence through the admitted model broker")
            run = await self.browser_service.create(data["_scope"], urls, data["title"][:120], f"workflow:{data['id']}", **options)
            try:
                await self.browser_service.wait_for_run(run["id"])
                run = await self.browser_service.snapshot(data["_scope"], run["id"])
                if run["status"] != "completed" or run.get("session_closed") is not True:
                    raise WorkflowServiceError("browser_evidence_unverified", 502)
                if options:
                    await self._event(data, "stagehand", "completed", worker_id="browser_researcher", model="gpt-6.1-sol", effort="low", detail="Browser source and screenshots read back; provider session closure verified")
                return {"pages": run["pages"], "evidence": [{"kind": "browserbase", "reference": f"/api/browserbase/research/{run['id']}", "bytes": len(_json(run["pages"]).encode())}]}
            except asyncio.CancelledError:
                await self.browser_service.cancel(data["_scope"], run["id"])
                raise

    async def _event(self, data, name, status, **details):
        allowed = ("worker_id", "model", "effort", "detail")
        event = {"name": str(name)[:80], "status": str(status)[:30], **{key: value if isinstance(value, (dict, list)) else str(value)[:1000] for key, value in details.items() if key in allowed}}
        if len(_json(event).encode()) > 8192:
            raise WorkflowServiceError("event_too_large")
        await self._storage("event", data["id"], data["_scope"], event)

    async def _native_start(self, data):
        if self.run_manager is None:
            return None
        with _native_context(data):
            return await self._native_start_scoped(data)

    async def _native_start_scoped(self, data):
        run_manager = self.run_manager
        if run_manager is None:
            return None
        native_user = _native_storage_user(data)
        thread_id = "wf_" + data["id"].replace("-", "")
        if self.thread_store is not None and await self.thread_store.get(thread_id, user_id=native_user) is None:
            await self.thread_store.create(thread_id, user_id=native_user, display_name=data["title"], metadata={"workflow_id": data["workflow_id"], "workflow_job_id": data["id"]})
        record = await run_manager.create_or_reject(
            thread_id,
            "lead_agent",
            user_id=native_user,
            model_name="gpt-6.1-sol",
            on_disconnect=DisconnectMode.continue_,
            metadata={"workflow_id": data["workflow_id"], "workflow_job_id": data["id"]},
            kwargs={"input": {"workflow_id": data["workflow_id"]}},
            idempotency_key=f"workflow:{data['id']}:{data.get('_resumes', 0)}",
        )
        if record.idempotency_reused:
            raise WorkflowServiceError("native_admission_uncertain", 409)
        try:
            record.task = asyncio.current_task()
            if await run_manager.try_start(record.run_id) != RunStartOutcome.started:
                raise WorkflowServiceError("native_run_cancelled", 409)
            baseline = {key: data["usage"].get(key, 0) for key in ("model_calls", "input_tokens", "output_tokens")}
            await self._storage("patch", data["id"], data["_scope"], {"native_run_id": record.run_id, "thread_id": thread_id, "_native_usage_start": baseline, "_native_storage_user": native_user})
            data.update(native_run_id=record.run_id, thread_id=thread_id, _native_usage_start=baseline, _native_storage_user=native_user)
            await self._journal(data, "run.start", "trace", {"chain": "momo_workflow", "workflow_id": data["workflow_id"], "framework": data["framework"]}, unique=True)
        except BaseException:
            cleanup = asyncio.create_task(self._native_finish(record, data, "interrupted", "native_admission_interrupted"))
            await asyncio.shield(cleanup)
            raise
        return record

    async def _journal(self, data, event_type, category, content, *, metadata=None, unique=False):
        if self.event_store is None or not data.get("native_run_id"):
            return
        method = self.event_store.put_if_absent if unique else self.event_store.put
        with _native_context(data):
            await method(
                thread_id=data["thread_id"],
                run_id=data["native_run_id"],
                event_type=event_type,
                category=category,
                content=content,
                metadata={"source_kind": "momo_workflow", "workflow_job_id": data["id"], "framework": data["framework"], **(metadata or {})},
            )

    async def _journal_model(self, data, result, kwargs):
        if self.event_store is None:
            return
        with _native_context(data):
            return await self._journal_model_scoped(data, result, kwargs)

    async def _journal_model_scoped(self, data, result, kwargs):
        from langchain_core.messages import AIMessage

        event_store = self.event_store
        if event_store is None:
            return

        context = result.get("_journal_context") or {"run_id": data.get("native_run_id"), "thread_id": data.get("thread_id")}
        if not context.get("run_id") or not context.get("thread_id"):
            return
        target = {**data, "native_run_id": context["run_id"], "thread_id": context["thread_id"]}
        usage = result["usage"]
        content = (
            {"code": result["error"], "usage": usage}
            if result.get("error")
            else AIMessage(
                content=_json(result["output"]),
                id=kwargs["call_id"],
                response_metadata={"model_name": result["model"]},
                usage_metadata={"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "total_tokens": usage["input_tokens"] + usage["output_tokens"]},
            ).model_dump()
        )
        async with self.journal_lock:
            rows = await event_store.list_events(target["thread_id"], target["native_run_id"], limit=100, user_id=_native_storage_user(data))
            if any(row.get("metadata", {}).get("call_id") == kwargs["call_id"] and row.get("event_type") in ("llm.ai.response", "llm.error") for row in rows):
                return
            await self._journal(
                target,
                "llm.error" if result.get("error") else "llm.ai.response",
                "trace" if result.get("error") else "message",
                content,
                metadata={"caller": kwargs["role"], "worker_id": kwargs["worker_id"], "call_id": kwargs["call_id"], "model_name": result["model"], "reasoning_effort": result["effort"]},
            )

    async def _native_finish(self, record, data, status, error=None):
        if record is None:
            return
        with _native_context(data):
            return await self._native_finish_scoped(record, data, status, error)

    async def _native_finish_scoped(self, record, data, status, error=None):
        run_manager = self.run_manager
        if run_manager is None:
            raise WorkflowServiceError("native_runtime_unavailable", 503)
        state = RunStatus.success if status == "completed" else RunStatus.interrupted if status in ("cancelled", "interrupted") else RunStatus.error
        baseline = data.get("_native_usage_start", {})
        usage = {key: max(0, data["usage"][key] - baseline.get(key, 0)) for key in ("model_calls", "input_tokens", "output_tokens")}
        await run_manager.update_run_completion(
            record.run_id,
            status=state.value,
            total_input_tokens=usage["input_tokens"],
            total_output_tokens=usage["output_tokens"],
            total_tokens=usage["input_tokens"] + usage["output_tokens"],
            llm_call_count=usage["model_calls"],
            last_ai_message=_json(data.get("output"))[:16000],
            token_usage_by_model={"gpt-6.1-sol": {"input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"]}},
        )
        await run_manager.set_status_if_not_cancelled(record.run_id, state, error=error, stop_reason="workflow_" + status)
        await self._journal(
            data, "run.end", "outputs", {"accepted": data.get("accepted", False), "status": status, "artifact": data.get("artifact"), "usage": _public(data)["usage"]}, metadata={"status": state.value, "error": error}, unique=True
        )

    async def _run(self, data):
        from deerflow.workflows.catalog import get_workflow

        record = None
        token = set_storage_context(WorkspaceStorageContext(data["_actor"], data["_organization"], data["_storage_user"]))
        try:
            current = await self._storage("get", data["id"], data["_scope"])
            if current["status"] != "running":
                return
            await self._authorize(data)
            definition = get_workflow(data["workflow_id"])
            if hashlib.sha256(_json(_definition_dict(definition)).encode()).hexdigest() != data["_definition_hash"]:
                raise WorkflowServiceError("workflow_revision_changed", 409)
            engine = self.engine
            if engine is None:
                raise WorkflowServiceError("workflow_runtime_unavailable", 503)
            record = await self._native_start(data)
            async with asyncio.timeout(600):
                result = await engine.execute(
                    definition,
                    data["_inputs"],
                    run_id=data["id"],
                    scope=data["_scope"],
                    framework=data["framework"],
                    model_call=lambda **kwargs: self._model(data, **kwargs),
                    browser_call=lambda urls: self._browser(data, urls),
                    event=lambda name, status, **details: self._event(data, name, status, **details),
                    resume=data.get("_resume", False),
                )
            if result.get("accepted") is not True:
                raise WorkflowServiceError("acceptance_failed", 422)
            await self._authorize(data)
            await self._write_artifact(data, result)
            final = await self._storage("terminal", data["id"], data["_scope"], {"status": "completed", "accepted": True, "output": result["output"], "evidence": result.get("evidence", []), "error": None})
            await self._native_finish(record, final, final["status"])
        except asyncio.CancelledError:
            status = "interrupted" if self.closing else "cancelled"
            final = await self._storage("terminal", data["id"], data["_scope"], {"status": status, "accepted": False, "error": "interrupted_by_shutdown" if self.closing else "cancelled"})
            await self._native_finish(record, final, final["status"], final.get("error"))
        except Exception as error:
            cause = error
            while not isinstance(cause, WorkflowServiceError) and cause.__cause__ is not None:
                cause = cause.__cause__
            code = getattr(cause, "code", "workflow_execution_failed")
            if not isinstance(code, str) or not re.fullmatch(r"[a-z0-9_]{1,80}", code):
                code = "workflow_execution_failed"
            final = await self._storage("terminal", data["id"], data["_scope"], {"status": "failed", "accepted": False, "error": code})
            await self._native_finish(record, final, final["status"], code)
        finally:
            reset_storage_context(token)

    async def _write_artifact(self, data, result):
        raw = _json({"workflow_id": data["workflow_id"], "run_id": data["id"], "framework": data["framework"], **result}).encode()
        if len(raw) > MAX_ARTIFACT:
            raise WorkflowServiceError("artifact_too_large", 413)
        target = self.artifact_dir / f"{data['id']}.json"

        def write():
            if target.is_symlink():
                raise WorkflowServiceError("unsafe_state_path", 503)
            if target.exists():
                if not target.is_file() or target.stat().st_size > MAX_ARTIFACT or target.read_bytes() != raw:
                    raise WorkflowServiceError("artifact_identity_conflict", 409)
            else:
                temporary = target.with_suffix(f".{uuid.uuid4().hex}.part")
                try:
                    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(raw)
                        handle.flush()
                        os.fsync(handle.fileno())
                    # Link a complete immutable file; never overwrite an
                    # earlier artifact or follow a hostile target symlink.
                    try:
                        os.link(temporary, target)
                    except FileExistsError:
                        if target.is_symlink() or not target.is_file() or target.read_bytes() != raw:
                            raise WorkflowServiceError("artifact_identity_conflict", 409) from None
                finally:
                    temporary.unlink(missing_ok=True)
            if target.read_bytes() != raw:
                raise WorkflowServiceError("artifact_readback_failed", 502)

        task = asyncio.create_task(asyncio.to_thread(write))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        await self._storage("patch", data["id"], data["_scope"], {"artifact": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}})

    async def artifact(self, owner, run_id):
        data = await self._storage("get", run_id, owner)
        if not data.get("artifact") or data["status"] != "completed" or data.get("accepted") is not True:
            raise WorkflowServiceError("artifact_unavailable", 404)
        target = self.artifact_dir / f"{data['id']}.json"

        def read():
            if target.is_symlink() or not target.is_file() or target.stat().st_size > MAX_ARTIFACT:
                raise WorkflowServiceError("artifact_readback_failed", 502)
            content = target.read_bytes()
            if len(content) != data["artifact"]["bytes"] or hashlib.sha256(content).hexdigest() != data["artifact"]["sha256"]:
                raise WorkflowServiceError("artifact_readback_failed", 502)
            return content

        return await asyncio.to_thread(read)

    async def cancel(self, owner, run_id):
        # Terminalize atomically before cancellation can interrupt cleanup. A
        # second cancel caller sees the terminal state and cannot cancel cleanup.
        data, changed = await self._storage("cancel", run_id, owner)
        if not changed:
            return _public(data)
        task = self.tasks.get(run_id)
        if task is not None:
            task.cancel()
            await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        return await self.snapshot(owner, run_id)

    async def resume(self, owner, run_id):
        data = await self._storage("resume", run_id, owner)
        self._wake()
        return _public(data)

    async def aclose(self):
        self.closing = True
        if self.pump_task is not None:
            await asyncio.gather(self.pump_task, return_exceptions=True)
        tasks = list(self.tasks.values())
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.shield(asyncio.gather(*tasks, return_exceptions=True))
        if self.lease is not None:
            await asyncio.to_thread(self.lease.close)
            self.lease = None
        if hasattr(self.adapter, "aclose"):
            await self.adapter.aclose()
        self.started = False
