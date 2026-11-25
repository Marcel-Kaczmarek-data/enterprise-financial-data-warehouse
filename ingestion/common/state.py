"""Persistent ingestion state: watermarks, batch audit and the file registry.

Backends: PostgreSQL schema ``ingestion_meta`` (default, docker) or SQLite (no-docker / unit tests).
Watermarks are advanced only by :meth:`StateStore.complete_batch`, which runs after the batch's
data files and manifest are durably written to object storage.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finance_common.config import local_config, repo_path

DDL = [
    """CREATE TABLE IF NOT EXISTS {s}watermarks (
        source_system TEXT NOT NULL, source_table TEXT NOT NULL,
        watermark_ts TEXT, watermark_key TEXT, batch_id TEXT, updated_at TEXT NOT NULL,
        PRIMARY KEY (source_system, source_table))""",
    """CREATE TABLE IF NOT EXISTS {s}batches (
        batch_id TEXT PRIMARY KEY, source_system TEXT NOT NULL, source_table TEXT NOT NULL,
        extraction_mode TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
        watermark_from TEXT, watermark_to TEXT, rows_extracted INTEGER, rows_source INTEGER,
        rows_quarantined INTEGER, object_keys TEXT, error TEXT)""",
    """CREATE TABLE IF NOT EXISTS {s}file_registry (
        checksum_sha256 TEXT PRIMARY KEY, source_system TEXT NOT NULL, original_name TEXT NOT NULL,
        status TEXT NOT NULL, batch_id TEXT, object_key TEXT, rows_valid INTEGER, rows_quarantined INTEGER,
        registered_at TEXT NOT NULL, detail TEXT)""",
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_batch_id(source: str, table: str) -> str:
    return f"{source}-{table}-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


@dataclass
class Watermark:
    ts: str | None
    key: str | None


class StateStore:
    def __init__(self, backend: str | None = None, sqlite_path: Path | None = None) -> None:
        cfg = local_config()["metadata_db"]
        self.backend = backend or cfg["backend"]
        if self.backend == "postgres":
            import psycopg

            pg = local_config()["source_postgres"]
            self._conn: Any = psycopg.connect(
                host=pg["host"],
                port=int(pg["port"]),
                dbname=pg["database"],
                user=pg["user"],
                password=pg["password"],
                autocommit=True,
            )
            self.prefix, self.ph = f"{cfg['schema']}.", "%s"
            self._conn.execute(f"CREATE SCHEMA IF NOT EXISTS {cfg['schema']}")
        else:
            path = sqlite_path or repo_path(cfg["sqlite_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(path, isolation_level=None)
            self.prefix, self.ph = "", "?"
        for ddl in DDL:
            self._exec(ddl.format(s=self.prefix))

    def _exec(self, sql: str, params: tuple = ()) -> list[tuple]:
        sql = sql.replace("?", self.ph)
        cur = self._conn.execute(sql, params)
        try:
            return list(cur.fetchall())
        except Exception:  # statements without a result set
            return []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self.backend == "postgres":
            with self._conn.transaction():
                yield
        else:
            self._conn.execute("BEGIN")
            try:
                yield
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # ---------------------------------------------------------------------------- watermarks
    def get_watermark(self, source: str, table: str) -> Watermark:
        rows = self._exec(
            f"SELECT watermark_ts, watermark_key FROM {self.prefix}watermarks "
            "WHERE source_system = ? AND source_table = ?",
            (source, table),
        )
        return Watermark(*rows[0]) if rows else Watermark(None, None)

    def reset_watermark(self, source: str, table: str) -> None:
        self._exec(f"DELETE FROM {self.prefix}watermarks WHERE source_system = ? AND source_table = ?", (source, table))

    # -------------------------------------------------------------------------------- batches
    def start_batch(self, source: str, table: str, mode: str, wm_from: str | None) -> str:
        batch_id = new_batch_id(source, table)
        self._exec(
            f"INSERT INTO {self.prefix}batches (batch_id, source_system, source_table, extraction_mode, status, "
            "started_at, watermark_from) VALUES (?, ?, ?, ?, 'RUNNING', ?, ?)",
            (batch_id, source, table, mode, now_iso(), wm_from),
        )
        return batch_id

    def complete_batch(
        self,
        batch_id: str,
        source: str,
        table: str,
        wm_to: Watermark,
        rows: int,
        rows_source: int | None,
        rows_quarantined: int,
        object_keys: list[str],
    ) -> None:
        """Mark the batch durable and advance the watermark atomically."""
        with self.transaction():
            self._exec(
                f"UPDATE {self.prefix}batches SET status = 'SUCCEEDED', finished_at = ?, watermark_to = ?, "
                "rows_extracted = ?, rows_source = ?, rows_quarantined = ?, object_keys = ? WHERE batch_id = ?",
                (now_iso(), wm_to.ts, rows, rows_source, rows_quarantined, json.dumps(object_keys), batch_id),
            )
            if wm_to.ts is not None:
                self._exec(
                    f"DELETE FROM {self.prefix}watermarks WHERE source_system = ? AND source_table = ?", (source, table)
                )
                self._exec(
                    f"INSERT INTO {self.prefix}watermarks (source_system, source_table, watermark_ts, "
                    "watermark_key, batch_id, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (source, table, wm_to.ts, wm_to.key, batch_id, now_iso()),
                )

    def fail_batch(self, batch_id: str, error: str) -> None:
        self._exec(
            f"UPDATE {self.prefix}batches SET status = 'FAILED', finished_at = ?, error = ? WHERE batch_id = ?",
            (now_iso(), error[:2000], batch_id),
        )

    def batches(self) -> list[dict[str, Any]]:
        cols = [
            "batch_id",
            "source_system",
            "source_table",
            "extraction_mode",
            "status",
            "started_at",
            "finished_at",
            "watermark_from",
            "watermark_to",
            "rows_extracted",
            "rows_source",
            "rows_quarantined",
            "error",
        ]
        rows = self._exec(f"SELECT {', '.join(cols)} FROM {self.prefix}batches ORDER BY started_at")
        return [dict(zip(cols, r, strict=True)) for r in rows]

    # -------------------------------------------------------------------------- file registry
    def file_status(self, checksum: str) -> tuple[str, str] | None:
        rows = self._exec(
            f"SELECT status, original_name FROM {self.prefix}file_registry WHERE checksum_sha256 = ?", (checksum,)
        )
        return (rows[0][0], rows[0][1]) if rows else None

    def register_file(
        self,
        checksum: str,
        source: str,
        name: str,
        status: str,
        batch_id: str | None,
        object_key: str | None,
        rows_valid: int,
        rows_quarantined: int,
        detail: str = "",
    ) -> None:
        self._exec(f"DELETE FROM {self.prefix}file_registry WHERE checksum_sha256 = ?", (checksum,))
        self._exec(
            f"INSERT INTO {self.prefix}file_registry (checksum_sha256, source_system, original_name, status, "
            "batch_id, object_key, rows_valid, rows_quarantined, registered_at, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                checksum,
                source,
                name,
                status,
                batch_id,
                object_key,
                rows_valid,
                rows_quarantined,
                now_iso(),
                detail[:2000],
            ),
        )

    def files(self) -> list[dict[str, Any]]:
        cols = [
            "checksum_sha256",
            "source_system",
            "original_name",
            "status",
            "batch_id",
            "object_key",
            "rows_valid",
            "rows_quarantined",
            "registered_at",
            "detail",
        ]
        rows = self._exec(f"SELECT {', '.join(cols)} FROM {self.prefix}file_registry ORDER BY registered_at")
        return [dict(zip(cols, r, strict=True)) for r in rows]

    def close(self) -> None:
        self._conn.close()
