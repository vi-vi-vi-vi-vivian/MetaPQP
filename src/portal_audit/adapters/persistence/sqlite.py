"""Small SQLite job repository for the local MVP."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class SQLiteAuditJobRepository:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def create(self, job_id: str, request: Mapping[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO audit_jobs VALUES (?, ?, ?, NULL, NULL, ?, ?)",
                (job_id, "pending", json.dumps(dict(request), default=str), now, now),
            )

    def _update(
        self, job_id: str, status: str, result: Any = None, error: str | None = None
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE audit_jobs SET status=?, result_json=?, error=?, updated_at=? WHERE job_id=?",
                (
                    status,
                    json.dumps(result, ensure_ascii=False, default=str)
                    if result is not None
                    else None,
                    error,
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )

    def mark_running(self, job_id: str) -> None:
        self._update(job_id, "running")

    def complete(self, job_id: str, result: Mapping[str, Any]) -> None:
        self._update(job_id, "completed", dict(result))

    def fail(self, job_id: str, error: str) -> None:
        self._update(job_id, "failed", error=error)
