from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


@dataclass(frozen=True)
class Task:
    task_id: str
    workflow_id: str
    prompt_text: str
    chat_id: str
    message_id: str
    status: str
    prompt_id: str | None = None
    client_id: str | None = None
    progress_message: str | None = None
    progress_percent: int | None = None
    output_path: str | None = None
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    card_message_id: str | None = None


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def create(self, workflow_id: str, prompt_text: str, chat_id: str, message_id: str) -> Task:
        task_id = uuid.uuid4().hex[:12]
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                  task_id, workflow_id, prompt_text, chat_id, message_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, workflow_id, prompt_text, chat_id, message_id, "queued", now, now),
            )
        return self.get(task_id)

    def get(self, task_id: str) -> Task:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return _row_to_task(row)

    def set_started(self, task_id: str, prompt_id: str, client_id: str) -> None:
        self._update(task_id, status="running", prompt_id=prompt_id, client_id=client_id)

    def set_card_message_id(self, task_id: str, card_message_id: str) -> None:
        self._update(task_id, card_message_id=card_message_id)

    def recent(self, limit: int = 10, chat_id: str | None = None) -> list[Task]:
        with self._connect() as conn:
            if chat_id is not None:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
                    (chat_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [_row_to_task(row) for row in rows]

    def set_progress(self, task_id: str, message: str, percent: int | None = None) -> None:
        self._update(task_id, progress_message=message, progress_percent=percent)

    def set_done(
        self,
        task_id: str,
        status: str,
        output_paths: list[str] | None = None,
        error: str | None = None,
    ) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError(f"invalid terminal status: {status}")
        encoded = json.dumps(output_paths) if output_paths else None
        self._update(task_id, status=status, output_path=encoded, error=error)

    def count_active(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS total FROM tasks WHERE status IN ('queued', 'running')"
            ).fetchone()
        return int(row["total"])

    def _update(self, task_id: str, **fields: object) -> None:
        fields["updated_at"] = _now()
        assignments = ", ".join(f"{name} = ?" for name in fields)
        values = list(fields.values())
        values.append(task_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE tasks SET {assignments} WHERE task_id = ?", values)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                  task_id TEXT PRIMARY KEY,
                  workflow_id TEXT NOT NULL,
                  prompt_text TEXT NOT NULL,
                  chat_id TEXT NOT NULL,
                  message_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  prompt_id TEXT,
                  client_id TEXT,
                  progress_message TEXT,
                  progress_percent INTEGER,
                  output_path TEXT,
                  error TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  card_message_id TEXT
                )
                """
            )
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN card_message_id TEXT")
            except sqlite3.OperationalError:
                pass

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def parse_output_paths(task: Task) -> list[str]:
    if not task.output_path:
        return []
    try:
        data = json.loads(task.output_path)
    except json.JSONDecodeError:
        return [task.output_path]
    if isinstance(data, list):
        return [str(p) for p in data]
    return [str(data)]


def format_task(task: Task) -> str:
    lines = [
        f"任务 {task.task_id}",
        f"workflow: {task.workflow_id}",
        f"状态: {task.status}",
    ]
    if task.progress_message:
        progress = task.progress_message
        if task.progress_percent is not None:
            progress = f"{progress} ({task.progress_percent}%)"
        lines.append(f"进度: {progress}")
    if task.error:
        lines.append(f"错误: {task.error}")
    paths = parse_output_paths(task)
    if paths:
        lines.append(f"输出: {len(paths)} 张")
        lines.extend(f"  {p}" for p in paths)
    return "\n".join(lines)


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(**{key: row[key] for key in row.keys()})


def _now() -> str:
    return datetime.now(UTC).isoformat()
