"""SQLite job history and the single-worker generation queue."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from reelpress.config import Settings
from reelpress.errors import ReelPressError
from reelpress.models import GenerateParams, PipelineResult

ACTIVE = {"queued", "running", "publishing"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_user_time(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ReelPressError("发布时间格式不正确。请使用 2026-10-10T20:00。") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    topic: str
    status: str
    stage: str
    progress: int
    params: dict[str, Any]
    result: dict[str, Any]
    error: str
    created_at: str
    updated_at: str
    publish_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "params": self.params,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "publish_at": self.publish_at,
        }


class JobStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    params_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    publish_at TEXT
                )
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def create(self, params: GenerateParams) -> Job:
        job_id = uuid.uuid4().hex[:12]
        stamp = now_iso()
        publish_at = parse_user_time(params.publish_at) if params.publish_at else None
        params.publish_at = publish_at
        record = (
            job_id,
            params.topic.strip() or "未命名",
            "queued",
            "pending",
            0,
            json.dumps(params.to_dict(), ensure_ascii=False),
            "{}",
            "",
            stamp,
            stamp,
            publish_at,
        )
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO jobs (
                    id, topic, status, stage, progress, params_json, result_json,
                    error, created_at, updated_at, publish_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                record,
            )
            self._conn.commit()
        job = self.get(job_id)
        assert job is not None
        return job

    def update(self, job_id: str, **fields: Any) -> Job:
        allowed = {
            "status",
            "stage",
            "progress",
            "error",
            "publish_at",
            "topic",
        }
        sets = ["updated_at = ?"]
        values: list[Any] = [now_iso()]
        if "params" in fields:
            sets.append("params_json = ?")
            values.append(json.dumps(fields["params"], ensure_ascii=False))
        if "result" in fields:
            sets.append("result_json = ?")
            values.append(json.dumps(fields["result"], ensure_ascii=False))
        for key, value in fields.items():
            if key in {"params", "result"}:
                continue
            if key not in allowed:
                raise ReelPressError(f"不能更新字段 {key}")
            sets.append(f"{key} = ?")
            values.append(value)
        values.append(job_id)
        with self._lock:
            cur = self._conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", values)
            self._conn.commit()
            if cur.rowcount == 0:
                raise ReelPressError("任务不存在。")
        job = self.get(job_id)
        assert job is not None
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list(self, limit: int = 50) -> list[Job]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            self._conn.commit()

    def claim_publish(self, job_id: str) -> bool:
        """Move a finished job to `publishing` exactly once."""
        allowed = ("queued", "running", "succeeded", "scheduled", "publish_failed")
        with self._lock:
            row = self._conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None or row["status"] not in allowed:
                return False
            self._conn.execute(
                "UPDATE jobs SET status = ?, stage = ?, updated_at = ? WHERE id = ?",
                ("publishing", "publish", now_iso(), job_id),
            )
            self._conn.commit()
            return True

    def due_for_publish(self, moment: datetime | None = None) -> list[Job]:
        current = (moment or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM jobs
                WHERE status = 'scheduled' AND publish_at IS NOT NULL AND publish_at <= ?
                ORDER BY publish_at ASC
                """,
                (current,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        topic=row["topic"],
        status=row["status"],
        stage=row["stage"],
        progress=row["progress"],
        params=json.loads(row["params_json"] or "{}"),
        result=json.loads(row["result_json"] or "{}"),
        error=row["error"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        publish_at=row["publish_at"],
    )


SettingsProvider = Callable[[], Settings]


class JobRunner:
    """One generation at a time. A side thread publishes jobs when they are due."""

    def __init__(self, store: JobStore, settings_provider: SettingsProvider) -> None:
        self.store = store
        self.settings_provider = settings_provider
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._loop, name="reelpress-jobs", daemon=True)
        self._wake = threading.Event()
        self._queue: list[str] = []
        self._lock = threading.Lock()

    def start(self) -> None:
        if not self._worker.is_alive():
            self._worker.start()
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._schedule_loop, name="reelpress-schedule", daemon=True)
            self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()

    def submit(self, job_id: str) -> None:
        with self._lock:
            if job_id not in self._queue:
                self._queue.append(job_id)
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=1.0)
            self._wake.clear()
            while not self._stop.is_set():
                with self._lock:
                    if not self._queue:
                        break
                    job_id = self._queue.pop(0)
                self._execute(job_id)

    def _schedule_loop(self) -> None:
        while not self._stop.wait(5):
            try:
                self.publish_due()
            except Exception:
                # A bad row should not kill the scheduler. The job keeps its error.
                continue

    def publish_due(self) -> None:
        from reelpress.publish import publish_job

        for job in self.store.due_for_publish():
            publish_job(job.id, self.store, self.settings_provider())

    def _execute(self, job_id: str) -> None:
        from reelpress.pipeline import run_pipeline
        from reelpress.publish import publish_job

        job = self.store.get(job_id)
        if job is None or job.status in {"running", "publishing"}:
            return
        settings = self.settings_provider()
        params = GenerateParams.from_dict(job.params)
        self.store.update(job_id, status="running", stage="script", progress=1, error="")

        def on_progress(stage: str, value: int, _message: str) -> None:
            # Publishing is reserved for after a successful render.
            shown = min(value, 95) if params.publish or params.publish_at else value
            self.store.update(job_id, stage=stage, progress=shown, status="running")

        try:
            result = run_pipeline(
                params,
                settings,
                settings.jobs_dir / job_id,
                on_progress=on_progress,
            )
        except ReelPressError as exc:
            self.store.update(job_id, status="failed", stage="failed", error=str(exc))
            return
        except Exception as exc:
            self.store.update(job_id, status="failed", stage="failed", error=f"生成失败：{exc}")
            return

        self.store.update(job_id, result=result.to_dict(), stage=result.stopped_at, progress=96)
        if params.stop_at != "video":
            self.store.update(job_id, status="succeeded", progress=100, stage=result.stopped_at)
            return
        if not params.publish and not params.publish_at:
            self.store.update(job_id, status="succeeded", progress=100, stage="done")
            return
        if params.publish_at:
            when = parse_user_time(params.publish_at)
            if when and when > now_iso():
                self.store.update(
                    job_id,
                    status="scheduled",
                    stage="publish",
                    progress=100,
                    publish_at=when,
                )
                return
        if params.platforms:
            publish_job(job_id, self.store, settings)
        else:
            self.store.update(job_id, status="succeeded", progress=100, stage="done")
