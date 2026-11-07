from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from .diagnostic_events import record, request_id, traced
from .resource_scope import scoped_write_key

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = Path(os.environ.get("ZAGENT_TUNNEL_RUNTIME_DIR", str(ROOT / "runtime"))).resolve()
RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = RUNTIME_DIR / "tasks.db"

TERMINAL = {"succeeded", "failed", "cancelled", "orphaned"}
INTERACTIVE_PRIORITIES = {0, 1}


class PreDispatchRejected(RuntimeError):
    """Trusted executor preflight rejected before backend invocation; no effect was dispatched."""



def now() -> float:
    return time.time()


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def upstream_error_summary(result: Any, limit: int = 1000) -> str:
    if not isinstance(result, dict):
        return ""
    domain_failed = result.get("ok") is False
    structured = result.get("structuredContent")
    domain_failed = domain_failed or (isinstance(structured, dict) and structured.get("ok") is False)
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                value = json.loads(item.get("text", ""))
                domain_failed = domain_failed or (isinstance(value, dict) and value.get("ok") is False)
            except (ValueError, TypeError):
                pass
    if result.get("isError") is not True and not domain_failed:
        return ""

    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())

    if not parts:
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            for key in ("error", "message", "result"):
                value = structured.get(key)
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
                    break

    summary = " | ".join(parts).strip()
    if not summary:
        summary = "Upstream MCP tool returned isError=true"

    if len(summary) > limit:
        summary = summary[: max(0, limit - 3)] + "..."

    return summary


@dataclass(order=True)
class QueueItem:
    priority: int
    seq: int
    task_id: str = field(compare=False)


@dataclass
class ExecContext:
    session_id: str
    request_id: str
    task_id: str
    trace_id: str
    idempotency_key: str
    profile_id: str
    resource_key: str
    access_mode: str
    priority: int
    service_id: str
    tool_name: str
    target_device_id: str
    executed_on: str
    operator_alias: str
    binding_revision: int
    binding_source: str
    execution_context: dict[str, Any] = field(default_factory=dict)


class TaskJournal:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
          task_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          request_id TEXT NOT NULL,
          trace_id TEXT NOT NULL,
          idempotency_key TEXT,
          profile_id TEXT,
          target_device_id TEXT,
          executed_on TEXT,
          operator_alias TEXT,
          binding_revision INTEGER,
          binding_source TEXT,
          service_id TEXT NOT NULL,
          tool_name TEXT NOT NULL,
          arguments_json TEXT NOT NULL,
          resource_key TEXT NOT NULL,
          access_mode TEXT NOT NULL,
          priority INTEGER NOT NULL,
          state TEXT NOT NULL,
          progress REAL NOT NULL DEFAULT 0,
          result_json TEXT,
          error TEXT,
          created_at REAL NOT NULL,
          updated_at REAL NOT NULL,
          started_at REAL,
          finished_at REAL,
          heartbeat_at REAL,
          retry_count INTEGER NOT NULL DEFAULT 0,
          queued_at REAL,
          recovered_at REAL
        )""")
        self.conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_idempotency
        ON tasks(idempotency_key)
        WHERE idempotency_key IS NOT NULL AND idempotency_key <> ''
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_state_priority "
            "ON tasks(state, priority, created_at)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_session "
            "ON tasks(session_id, created_at)"
        )
        columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        if "profile_id" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN profile_id TEXT")
        if "queued_at" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN queued_at REAL")
        if "recovered_at" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN recovered_at REAL")
        if "target_device_id" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN target_device_id TEXT")
        if "executed_on" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN executed_on TEXT")
        if "operator_alias" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN operator_alias TEXT")
        if "binding_revision" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN binding_revision INTEGER")
        if "binding_source" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN binding_source TEXT")
        if "execution_context_json" not in columns:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN execution_context_json TEXT NOT NULL DEFAULT '{}'")
        # Old owners remain archives; never adopt them into authenticated ownership.
        self.conn.execute("UPDATE tasks SET state='orphaned', error='LEGACY_OWNER_RECONCILIATION_REQUIRED' WHERE session_id NOT LIKE 'owner_v1_%' AND state NOT IN ('succeeded','failed','cancelled','orphaned')")
        self.conn.commit()
        self._lock = asyncio.Lock()

    async def create(self, row: dict[str, Any]) -> tuple[str, bool]:
        async with self._lock:
            key = row.get("idempotency_key") or ""
            if key:
                existing = self.conn.execute(
                    "SELECT * FROM tasks WHERE idempotency_key=?", (key,)
                ).fetchone()
                if existing:
                    if any(existing[k] != row.get(k) for k in ("session_id", "service_id", "tool_name", "arguments_json", "resource_key", "access_mode")):
                        raise ValueError("IDEMPOTENCY_CONFLICT")
                    before = json.loads(existing["execution_context_json"] or "{}")
                    after = json.loads(row.get("execution_context_json") or "{}")
                    if any(before.get(k) != after.get(k) for k in ("principal_id", "workspace_id", "device_id", "policy_revision", "required_scope", "public_tool", "effective_resources")):
                        raise ValueError("IDEMPOTENCY_CONFLICT")
                    return str(existing["task_id"]), False
            cols = ",".join(row.keys())
            qs = ",".join("?" for _ in row)
            self.conn.execute(
                f"INSERT INTO tasks ({cols}) VALUES ({qs})", tuple(row.values())
            )
            self.conn.commit()
            return str(row["task_id"]), True

    async def update(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = now()
        async with self._lock:
            assignments = ",".join(f"{k}=?" for k in fields)
            vals = list(fields.values()) + [task_id]
            self.conn.execute(
                f"UPDATE tasks SET {assignments} WHERE task_id=?", vals
            )
            self.conn.commit()

    async def get(self, task_id: str) -> dict[str, Any] | None:
        async with self._lock:
            row = self.conn.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    async def list(
        self, session_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        async with self._lock:
            if session_id:
                rows = self.conn.execute(
                    "SELECT * FROM tasks WHERE session_id=? "
                    "ORDER BY created_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    async def recover_incomplete(self) -> list[str]:
        async with self._lock:
            # In-memory credential authorizations cannot survive restart. No blind
            # replay, including a writer whose previous effect is uncertain.
            self.conn.execute("UPDATE tasks SET state='orphaned', error='RECOVERY_REQUIRED', updated_at=? WHERE state NOT IN ('succeeded','failed','cancelled','orphaned')", (now(),))
            self.conn.commit()
            return []



class ResourceLockManager:
    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._readers: dict[str, int] = {}
        self._writers: set[str] = set()

    @asynccontextmanager
    async def acquire(self, key: str, mode: str, *, subresource: str | None = None):
        key = key or "global"
        mode = "read" if mode == "read" else "write"
        # A narrow mutation leases installation READ + its exact file WRITE,
        # atomically, so installation-wide writers still exclude every writer.
        # No writer can interleave between the two acquisitions.
        narrow = mode == "write" and isinstance(subresource, str) and subresource.startswith("filespath:")
        started = now()
        async with self._cond:
            if narrow:
                await self._cond.wait_for(
                    lambda: key not in self._writers
                    and subresource not in self._writers
                    and self._readers.get(subresource, 0) == 0)
                self._readers[key] = self._readers.get(key, 0) + 1
                self._writers.add(subresource)
            elif mode == "read":
                await self._cond.wait_for(lambda: key not in self._writers)
                self._readers[key] = self._readers.get(key, 0) + 1
            else:
                await self._cond.wait_for(
                    lambda: key not in self._writers
                    and self._readers.get(key, 0) == 0)
                self._writers.add(key)
        wait_ms = (now() - started) * 1000
        try:
            yield wait_ms
        finally:
            async with self._cond:
                if narrow:
                    self._writers.discard(subresource)
                    count = self._readers.get(key, 0) - 1
                    if count <= 0: self._readers.pop(key, None)
                    else: self._readers[key] = count
                elif mode == "read":
                    count = self._readers.get(key, 0) - 1
                    if count <= 0: self._readers.pop(key, None)
                    else: self._readers[key] = count
                else:
                    self._writers.discard(key)
                self._cond.notify_all()


class Telemetry:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.max_events = 4000

    def emit(self, ctx: ExecContext, stage: str, **extra: Any) -> None:
        item = {
            "ts": now(),
            "stage": stage,
            "trace_id": ctx.trace_id,
            "session_id": ctx.session_id,
            "profile_id": ctx.profile_id or None,
            "request_id": ctx.request_id,
            "task_id": ctx.task_id,
            "service_id": ctx.service_id,
            "tool_name": ctx.tool_name,
            "target_device_id": ctx.target_device_id or None,
            "executed_on": ctx.executed_on or None,
            "operator_alias": ctx.operator_alias or None,
            "binding_revision": ctx.binding_revision or None,
            "binding_source": ctx.binding_source or None,
            **extra,
        }
        self.events.append(item)
        if len(self.events) > self.max_events:
            del self.events[: len(self.events) - self.max_events]

    def summary(self) -> dict[str, Any]:
        return {"event_count": len(self.events), "recent": self.events[-50:]}


class Orchestrator:
    def __init__(
        self,
        executor: Callable[
            [str, str, dict[str, Any], ExecContext],
            Awaitable[dict[str, Any]],
        ],
        journal_path: Path | None = None,
    ) -> None:
        self.executor = executor
        self.journal = TaskJournal(journal_path or DB_PATH)
        self.locks = ResourceLockManager()
        self._scoped_files_profile: str | None = None
        self.telemetry = Telemetry()

        self.interactive_queue: asyncio.PriorityQueue[QueueItem] = (
            asyncio.PriorityQueue()
        )
        self.background_queue: asyncio.PriorityQueue[QueueItem] = (
            asyncio.PriorityQueue()
        )
        self._queue_event = asyncio.Event()
        self._seq = 0

        self._workers: list[asyncio.Task] = []
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._cancel: set[str] = set()

        self.default_limits = {
            "zagent_files": 8,
            "zagent_browser": 4,
            "zagent_arcmap": 1,
        }
        self.interactive_reserve = {
            "zagent_files": 2,
            "zagent_browser": 1,
            "zagent_arcmap": 0,
        }
        self._agent_total_semaphores: dict[str, asyncio.Semaphore] = {}
        self._agent_background_semaphores: dict[str, asyncio.Semaphore] = {}

        self.total_workers = 8
        self.fast_lane_workers = 2
        self._stopping = False

    def configure(self, cfg: dict[str, Any] | None = None) -> None:
        cfg = cfg or {}
        limits = cfg.get("default_concurrency") or {}
        reserves = cfg.get("interactive_reserve") or {}
        for service_id, value in limits.items():
            self.default_limits[str(service_id)] = max(1, int(value))
        for service_id, value in reserves.items():
            total = self.default_limits.get(str(service_id), 4)
            self.interactive_reserve[str(service_id)] = max(
                0, min(int(value), max(0, total - 1))
            )
        self.total_workers = max(3, int(cfg.get("workers", self.total_workers)))
        self.fast_lane_workers = max(
            1,
            min(
                int(cfg.get("fast_lane_workers", self.fast_lane_workers)),
                self.total_workers - 1,
            ),
        )

    def _is_interactive(self, priority: int) -> bool:
        return priority in INTERACTIVE_PRIORITIES

    def _subresource(self, ctx: ExecContext, arguments: dict[str, Any]) -> str | None:
        if ctx.access_mode != "write":
            return None
        value = scoped_write_key(ctx.execution_context, ctx.service_id,
                                 ctx.tool_name, arguments)
        if not value:
            return None
        profile = ctx.execution_context["effective_resources"][0]["profile_id"]
        # Only one profile may ever use scoped writes until Router stops.
        # Other profiles remain global writers, even if their paths overlap.
        if self._scoped_files_profile is None:
            self._scoped_files_profile = profile
        if self._scoped_files_profile != profile:
            return None
        return value

    def queue_depth(self) -> int:
        return self.interactive_queue.qsize() + self.background_queue.qsize()

    def queue_depths(self) -> dict[str, int]:
        return {
            "interactive": self.interactive_queue.qsize(),
            "background": self.background_queue.qsize(),
            "total": self.queue_depth(),
        }

    def _total_semaphore(self, service_id: str) -> asyncio.Semaphore:
        if service_id not in self._agent_total_semaphores:
            limit = max(1, int(self.default_limits.get(service_id, 4)))
            self._agent_total_semaphores[service_id] = asyncio.Semaphore(limit)
        return self._agent_total_semaphores[service_id]

    def _background_semaphore(self, service_id: str) -> asyncio.Semaphore:
        if service_id not in self._agent_background_semaphores:
            total = max(1, int(self.default_limits.get(service_id, 4)))
            reserve = max(
                0,
                min(
                    int(self.interactive_reserve.get(service_id, 1)),
                    max(0, total - 1),
                ),
            )
            background_limit = max(1, total - reserve)
            self._agent_background_semaphores[service_id] = asyncio.Semaphore(
                background_limit
            )
        return self._agent_background_semaphores[service_id]

    @asynccontextmanager
    async def capacity(self, ctx: ExecContext):
        total = self._total_semaphore(ctx.service_id)
        if self._is_interactive(ctx.priority):
            async with total:
                yield
        else:
            background = self._background_semaphore(ctx.service_id)
            async with background:
                async with total:
                    yield

    async def start(
        self,
        workers: int | None = None,
        fast_lane_workers: int | None = None,
    ) -> None:
        if workers is not None:
            self.total_workers = max(3, int(workers))
        if fast_lane_workers is not None:
            self.fast_lane_workers = max(
                1, min(int(fast_lane_workers), self.total_workers - 1)
            )

        recovered = await self.journal.recover_incomplete()
        for task_id in recovered:
            row = await self.journal.get(task_id)
            if row:
                queued_at = now()
                await self.journal.update(
                    task_id,
                    state="queued",
                    queued_at=queued_at,
                    started_at=None,
                    finished_at=None,
                    heartbeat_at=queued_at,
                    progress=0.0,
                )
                await self._enqueue(
                    task_id, int(row["priority"]), emit_event=False
                )

        if self._workers:
            return

        self._stopping = False
        general_workers = self.total_workers - self.fast_lane_workers

        for i in range(self.fast_lane_workers):
            self._workers.append(
                asyncio.create_task(
                    self._worker(i, "fast"),
                    name=f"zagent-fast-worker-{i}",
                )
            )

        for i in range(general_workers):
            worker_id = self.fast_lane_workers + i
            self._workers.append(
                asyncio.create_task(
                    self._worker(worker_id, "general"),
                    name=f"zagent-general-worker-{worker_id}",
                )
            )

    async def stop(self) -> None:
        self._stopping = True
        self._queue_event.set()

        for runner in list(self._active_tasks.values()):
            if not runner.done():
                runner.cancel()

        for worker in self._workers:
            worker.cancel()

        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        if self._active_tasks:
            await asyncio.gather(
                *list(self._active_tasks.values()), return_exceptions=True
            )

        self._workers.clear()
        self._active_tasks.clear()

    def context(
        self,
        service_id: str,
        tool_name: str,
        meta: dict[str, Any] | None = None,
        *,
        task_id: str | None = None,
    ) -> ExecContext:
        meta = meta or {}
        return ExecContext(
            session_id=str(meta.get("session_id") or uid("ses")),
            request_id=str(meta.get("request_id") or uid("req")),
            task_id=str(task_id or meta.get("task_id") or uid("tsk")),
            trace_id=str(meta.get("trace_id") or uid("trc")),
            idempotency_key=str(meta.get("idempotency_key") or ""),
            profile_id=str(meta.get("profile_id") or ""),
            resource_key=str(
                meta.get("resource_key") or f"{service_id}:{tool_name}"
            ),
            access_mode=str(meta.get("access_mode") or "write"),
            priority=max(0, min(int(meta.get("priority", 2)), 3)),
            service_id=service_id,
            tool_name=tool_name,
            target_device_id=str(meta.get("target_device_id") or ""),
            executed_on=str(meta.get("executed_on") or ""),
            operator_alias="",
            binding_revision=0,
            binding_source="",
            execution_context=dict(meta.get("execution_context") or {}),
        )

    async def execute_fast(
        self,
        service_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = self.context(service_id, tool_name, meta)
        stamp = now()
        fast_row = {
            "execution_context_json": json.dumps(ctx.execution_context, sort_keys=True),
            "task_id": ctx.task_id,
            "session_id": ctx.session_id,
            "request_id": ctx.request_id,
            "trace_id": ctx.trace_id,
            "idempotency_key": "",
            "profile_id": ctx.profile_id,
            "target_device_id": ctx.target_device_id,
            "executed_on": ctx.executed_on,
            "operator_alias": ctx.operator_alias,
            "binding_revision": ctx.binding_revision,
            "binding_source": ctx.binding_source,
            "service_id": service_id,
            "tool_name": tool_name,
            "arguments_json": json.dumps(arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            "resource_key": ctx.resource_key,
            "access_mode": ctx.access_mode,
            "priority": ctx.priority,
            "state": "running",
            "progress": 0.05,
            "created_at": stamp,
            "updated_at": stamp,
            "started_at": stamp,
            "heartbeat_at": stamp,
        }
        await self.journal.create(fast_row)
        current = asyncio.current_task()
        if current is not None:
            self._active_tasks[ctx.task_id] = current
        self.telemetry.emit(ctx, "received")
        self.telemetry.emit(ctx, "validated")
        started = now()
        await self.journal.update(
            ctx.task_id, state="waiting_capacity", progress=0.01, heartbeat_at=started
        )

        async with self.capacity(ctx):
            capacity_wait_ms = (now() - started) * 1000
            await self.journal.update(ctx.task_id, state="waiting_lock", progress=0.03, heartbeat_at=now())
            async with self.locks.acquire(
                ctx.resource_key, ctx.access_mode,
                subresource=self._subresource(ctx, arguments)
            ) as lock_wait_ms:
                self.telemetry.emit(
                    ctx,
                    "dispatched",
                    capacity_wait_ms=capacity_wait_ms,
                    lock_wait_ms=lock_wait_ms,
                )
                agent_started = now()
                await self.journal.update(ctx.task_id, state="running", progress=0.05, started_at=agent_started, heartbeat_at=agent_started)
                self.telemetry.emit(ctx, "agent_start")
                try:
                    result = await self.executor(
                        service_id, tool_name, arguments, ctx
                    )
                except asyncio.CancelledError:
                    finished = now()
                    await self.journal.update(ctx.task_id, state="cancelled", finished_at=finished, heartbeat_at=finished)
                    if current is not None and self._active_tasks.get(ctx.task_id) is current:
                        self._active_tasks.pop(ctx.task_id, None)
                    self._cancel.discard(ctx.task_id)
                    raise
                except Exception as exc:
                    finished = now()
                    await self.journal.update(ctx.task_id, state="failed", progress=1.0, error=str(exc), finished_at=finished, heartbeat_at=finished)
                    if current is not None and self._active_tasks.get(ctx.task_id) is current:
                        self._active_tasks.pop(ctx.task_id, None)
                    self._cancel.discard(ctx.task_id)
                    raise
                self.telemetry.emit(
                    ctx,
                    "agent_done",
                    agent_ms=(now() - agent_started) * 1000,
                )

        finished = now()
        upstream_error = upstream_error_summary(result)
        await self.journal.update(
            ctx.task_id,
            state="failed" if upstream_error else "succeeded",
            progress=1.0,
            result_json=json.dumps(result, ensure_ascii=False),
            error=upstream_error or None,
            finished_at=finished,
            heartbeat_at=finished,
        )
        if current is not None and self._active_tasks.get(ctx.task_id) is current:
            self._active_tasks.pop(ctx.task_id, None)
        self._cancel.discard(ctx.task_id)
        self.telemetry.emit(
            ctx, "response_sent", duration_ms=(finished - started) * 1000
        )
        return result

    async def _enqueue(
        self,
        task_id: str,
        priority: int,
        *,
        emit_event: bool = True,
        ctx: ExecContext | None = None,
    ) -> None:
        self._seq += 1
        item = QueueItem(priority, self._seq, task_id)
        if self._is_interactive(priority):
            await self.interactive_queue.put(item)
        else:
            await self.background_queue.put(item)
        self._queue_event.set()
        if emit_event and ctx is not None:
            self.telemetry.emit(
                ctx,
                "queued",
                queue_depth=self.queue_depth(),
                lane="interactive"
                if self._is_interactive(priority)
                else "background",
            )

    async def submit(
        self,
        service_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ctx = self.context(service_id, tool_name, meta)
        stamp = now()
        row = {
            "execution_context_json": json.dumps(ctx.execution_context, sort_keys=True),
            "task_id": ctx.task_id,
            "session_id": ctx.session_id,
            "request_id": ctx.request_id,
            "trace_id": ctx.trace_id,
            "idempotency_key": ctx.idempotency_key,
            "profile_id": ctx.profile_id,
            "target_device_id": ctx.target_device_id,
            "executed_on": ctx.executed_on,
            "operator_alias": ctx.operator_alias,
            "binding_revision": ctx.binding_revision,
            "binding_source": ctx.binding_source,
            "service_id": service_id,
            "tool_name": tool_name,
            "arguments_json": json.dumps(
                arguments or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ),
            "resource_key": ctx.resource_key,
            "access_mode": ctx.access_mode,
            "priority": ctx.priority,
            "state": "accepted",
            "progress": 0.0,
            "created_at": stamp,
            "updated_at": stamp,
        }
        task_id, created = await self.journal.create(row)
        if not created:
            existing = await self.journal.get(task_id)
            return {
                "accepted": False,
                "duplicate": True,
                "task_id": task_id,
                "task": self.public_task(existing),
            }

        queued_at = now()
        await self.journal.update(
            task_id,
            state="queued",
            queued_at=queued_at,
            heartbeat_at=queued_at,
        )
        await self._enqueue(
            task_id, ctx.priority, emit_event=True, ctx=ctx
        )
        return {
            "accepted": True,
            "task_id": task_id,
            "session_id": ctx.session_id,
            "request_id": ctx.request_id,
            "trace_id": ctx.trace_id,
            "target_device_id": ctx.target_device_id or None,
            "executed_on": ctx.executed_on or None,
            "operator_alias": ctx.operator_alias or None,
            "binding_revision": ctx.binding_revision or None,
            "binding_source": ctx.binding_source or None,
            "state": "queued",
            "lane": "interactive"
            if self._is_interactive(ctx.priority)
            else "background",
        }

    async def _propagate_agent_cancel(self, row: dict[str, Any]) -> dict[str, Any] | None:
        """Propagate cancellation to agents that keep work alive after HTTP disconnect."""
        service_id = str(row.get("service_id") or "")
        tool_name = str(row.get("tool_name") or "")
        if (
            service_id not in {"zagent_files", "zagent_files_v3"}
            or str(row.get("state")) != "running"
        ):
            return None

        command_tools = {
            "files_powershell_run",
            "files_exec_command",
            "files_node",
            "files_npm",
            "files_npx",
            "files_git",
            "files_build",
            "files_test",
        }
        if tool_name == "files_copy_batch_between_profiles":
            cancel_tool = "files_operation_cancel"
        elif tool_name in command_tools:
            cancel_tool = "files_command_cancel"
        else:
            return None

        ctx = self.context(
            service_id,
            cancel_tool,
            {
                "session_id": row.get("session_id"),
                "request_id": uid("cancel_req"),
                "trace_id": row.get("trace_id"),
                "target_device_id": row.get("target_device_id"),
                "executed_on": row.get("executed_on"),
                "operator_alias": row.get("operator_alias"),
                "binding_revision": row.get("binding_revision"),
                "binding_source": row.get("binding_source"),
                "resource_key": f"filesv3:cancel:{row.get('task_id')}",
                "access_mode": "write",
                "priority": 0,
            },
            task_id=str(row.get("task_id")),
        )
        args = {
            "session_id": str(row.get("session_id") or ""),
            "task_id": str(row.get("task_id") or ""),
        }
        last: dict[str, Any] | None = None
        for delay in (0.0, 0.05, 0.2):
            if delay:
                await asyncio.sleep(delay)
            try:
                result = await self.executor(
                    service_id,
                    cancel_tool,
                    args,
                    ctx,
                )
                last = result if isinstance(result, dict) else {"result": result}
                if not (isinstance(last, dict) and last.get("isError") is True):
                    return last
            except Exception as exc:
                last = {"error": str(exc)}
        return last

    async def cancel(self, task_id: str) -> dict[str, Any]:
        row = await self.journal.get(task_id)
        if not row:
            return {"ok": False, "error": "task not found"}
        if row["state"] in TERMINAL:
            return {
                "ok": False,
                "task_id": task_id,
                "state": row["state"],
                "error": "task already terminal",
            }

        self._cancel.add(task_id)
        runner = self._active_tasks.get(task_id)

        if runner is not None and not runner.done():
            await self.journal.update(
                task_id,
                state="cancelling",
                heartbeat_at=now(),
            )
            agent_cancel = await self._propagate_agent_cancel(row)
            # Do not cancel the awaiting Python thread/HTTP coroutine and release
            # its lock while an ArcPy/browser/file effect can still be executing.
            # Workflow/domain cooperative boundaries observe durable cancel intent.
            return {
                "ok": True,
                "task_id": task_id,
                "state": "cancelling",
                "cooperative": True,
                "agent_cancel": agent_cancel,
            }

        latest = await self.journal.get(task_id)
        if latest and latest["state"] in TERMINAL:
            return {
                "ok": False,
                "task_id": task_id,
                "state": latest["state"],
                "error": "task already terminal",
            }

        await self.journal.update(
            task_id,
            state="cancelled",
            finished_at=now(),
            heartbeat_at=now(),
        )
        return {
            "ok": True,
            "task_id": task_id,
            "state": "cancelled",
            "cooperative": False,
        }

    async def _get_general_item(
        self,
    ) -> tuple[asyncio.PriorityQueue[QueueItem], QueueItem]:
        while not self._stopping:
            try:
                return (
                    self.interactive_queue,
                    self.interactive_queue.get_nowait(),
                )
            except asyncio.QueueEmpty:
                pass

            try:
                return (
                    self.background_queue,
                    self.background_queue.get_nowait(),
                )
            except asyncio.QueueEmpty:
                pass

            self._queue_event.clear()

            if (
                not self.interactive_queue.empty()
                or not self.background_queue.empty()
            ):
                self._queue_event.set()
                continue

            await self._queue_event.wait()

        raise asyncio.CancelledError()

    async def _worker(self, worker_id: int, lane: str) -> None:
        while not self._stopping:
            if lane == "fast":
                queue = self.interactive_queue
                item = await queue.get()
            else:
                queue, item = await self._get_general_item()

            runner = asyncio.create_task(
                self._run_task(item.task_id, worker_id, lane),
                name=f"zagent-task-{item.task_id}",
            )
            self._active_tasks[item.task_id] = runner

            try:
                await runner
            except asyncio.CancelledError:
                if self._stopping:
                    raise
            finally:
                current = self._active_tasks.get(item.task_id)
                if current is runner:
                    self._active_tasks.pop(item.task_id, None)
                queue.task_done()

    @traced('job.scheduler', 'UNEXPECTED_ERROR')
    async def _run_task(
        self, task_id: str, worker_id: int, lane: str
    ) -> None:
        row = await self.journal.get(task_id)
        if (
            not row
            or row["state"] == "cancelled"
            or task_id in self._cancel
        ):
            return

        ctx = self.context(
            str(row["service_id"]),
            str(row["tool_name"]),
            {
                "session_id": row["session_id"],
                "request_id": row["request_id"],
                "trace_id": row["trace_id"],
                "idempotency_key": row["idempotency_key"],
                "profile_id": row.get("profile_id") or "",
                "target_device_id": row.get("target_device_id") or "",
                "executed_on": row.get("executed_on") or "",
                "operator_alias": "",
                "binding_revision": 0,
                "binding_source": "",
                "resource_key": row["resource_key"],
                "access_mode": row["access_mode"],
                "priority": row["priority"],
                "execution_context": json.loads(row.get("execution_context_json") or "{}"),
            },
            task_id=task_id,
        )
        args = json.loads(str(row["arguments_json"]))
        effect_started = False
        dequeued_at = now()
        queue_started_at = float(
            row.get("queued_at") or row["created_at"]
        )
        queue_wait_ms = max(
            0.0, (dequeued_at - queue_started_at) * 1000
        )

        try:
            await self.journal.update(
                task_id,
                state="waiting_capacity",
                progress=0.01,
                heartbeat_at=dequeued_at,
            )
            self.telemetry.emit(
                ctx,
                "waiting_capacity",
                worker_id=worker_id,
                lane=lane,
                queue_wait_ms=queue_wait_ms,
            )

            capacity_started = now()
            async with self.capacity(ctx):
                capacity_wait_ms = (now() - capacity_started) * 1000
                if task_id in self._cancel:
                    raise asyncio.CancelledError()

                await self.journal.update(
                    task_id,
                    state="waiting_lock",
                    progress=0.03,
                    heartbeat_at=now(),
                )
                self.telemetry.emit(
                    ctx,
                    "waiting_lock",
                    capacity_wait_ms=capacity_wait_ms,
                )

                async with self.locks.acquire(
                    ctx.resource_key, ctx.access_mode,
                    subresource=self._subresource(ctx, args)
                ) as lock_wait_ms:
                    if task_id in self._cancel:
                        raise asyncio.CancelledError()

                    started = now()
                    await self.journal.update(
                        task_id,
                        state="running",
                        started_at=started,
                        heartbeat_at=started,
                        progress=0.05,
                    )
                    self.telemetry.emit(
                        ctx,
                        "dispatched",
                        worker_id=worker_id,
                        lane=lane,
                        queue_wait_ms=queue_wait_ms,
                        capacity_wait_ms=capacity_wait_ms,
                        lock_wait_ms=lock_wait_ms,
                    )
                    self.telemetry.emit(ctx, "agent_start")

                    effect_started = True
                    result = await self.executor(
                        ctx.service_id, ctx.tool_name, args, ctx
                    )

                    agent_ms = (now() - started) * 1000
                    self.telemetry.emit(
                        ctx, "agent_done", agent_ms=agent_ms
                    )

            if task_id in self._cancel:
                raise asyncio.CancelledError()

            result_json = json.dumps(result, ensure_ascii=False)
            upstream_error = upstream_error_summary(result)
            terminal_state = "failed" if upstream_error else "succeeded"
            if upstream_error:
                record('job.upstream_result', 'ROUTER_UPSTREAM_UNAVAILABLE')
            finished = now()

            await self.journal.update(
                task_id,
                state=terminal_state,
                progress=1.0,
                result_json=result_json,
                error=upstream_error or None,
                finished_at=finished,
                heartbeat_at=finished,
            )
            self.telemetry.emit(
                ctx,
                "result_persisted",
                terminal_state=terminal_state,
                upstream_is_error=bool(upstream_error),
                payload_bytes=len(result_json.encode("utf-8")),
            )

        except PreDispatchRejected as exc:
            await self.journal.update(
                task_id, state="failed", error=str(exc),
                finished_at=now(), heartbeat_at=now(),
            )
            self.telemetry.emit(ctx, "pre_dispatch_rejected", error=str(exc))

        except asyncio.CancelledError:
            if self._stopping and task_id not in self._cancel:
                await self.journal.update(
                    task_id,
                    state="orphaned" if effect_started else "recovering",
                    heartbeat_at=now(),
                )
                self.telemetry.emit(
                    ctx, "interrupted_for_recovery", reason="router_stopping"
                )
            else:
                await self.journal.update(
                    task_id,
                    state="orphaned" if ctx.access_mode == "write" and effect_started else "cancelled",
                    finished_at=now(),
                    heartbeat_at=now(),
                )
                self.telemetry.emit(ctx, "cancelled")
            raise

        except Exception:
            correlation = request_id()
            record('job.execution', 'UNEXPECTED_ERROR', correlation)
            safe_error = 'Job execution failed. requestId=' + correlation
            await self.journal.update(
                task_id,
                state="orphaned" if ctx.access_mode == "write" and effect_started else "failed",
                error=safe_error,
                finished_at=now(),
                heartbeat_at=now(),
            )
            self.telemetry.emit(ctx, "agent_done", error=safe_error)

    def public_task(
        self, row: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not row:
            return None
        data = dict(row)
        context = json.loads(data.pop("execution_context_json", "{}") or "{}")
        for name in ("session_id", "operator_alias", "binding_revision", "binding_source", "idempotency_key"):
            data.pop(name, None)
        for name in ("principal_id", "workspace_id", "operation_id", "run_id"):
            if context.get(name):
                data[name] = context[name]
        args = data.pop("arguments_json", "{}")
        result = data.pop("result_json", None)
        data["arguments"] = json.loads(args or "{}")
        if result:
            try:
                data["result"] = json.loads(result)
            except Exception:
                data["result"] = result
        return data

    async def status(self, task_id: str) -> dict[str, Any]:
        row = await self.journal.get(task_id)
        return {"ok": bool(row), "task": self.public_task(row)}

    async def result(self, task_id: str) -> dict[str, Any]:
        row = await self.journal.get(task_id)
        if not row:
            return {"ok": False, "error": "task not found"}
        public = self.public_task(row)
        return {"ok": row["state"] == "succeeded", "task": public}

    async def list_tasks(
        self, session_id: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        rows = await self.journal.list(
            session_id=session_id,
            limit=max(1, min(limit, 200)),
        )
        return {
            "tasks": [self.public_task(r) for r in rows],
            "queue_depth": self.queue_depth(),
            "queue_depths": self.queue_depths(),
        }

    def runtime_status(self) -> dict[str, Any]:
        return {
            "queue_depth": self.queue_depth(),
            "queue_depths": self.queue_depths(),
            "workers": len(self._workers),
            "fast_lane_workers": self.fast_lane_workers,
            "general_workers": max(
                0, len(self._workers) - self.fast_lane_workers
            ),
            "active_tasks": len(self._active_tasks),
            "agent_limits": dict(self.default_limits),
            "interactive_reserve": dict(self.interactive_reserve),
        }
