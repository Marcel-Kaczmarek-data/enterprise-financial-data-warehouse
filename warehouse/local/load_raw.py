"""Load committed landing-zone batches into the local DuckDB raw layer (``finance_raw``).

Equivalent of Snowflake ``COPY INTO`` from an external stage with load history:

* Only batches with a published manifest are considered (the manifest is the commit point).
* Every data file's SHA-256 is verified against the manifest before loading (corruption check).
* ``finance_audit.raw_load_history`` records each manifest; reloading is a no-op (idempotent).
* Raw tables are append-only, one row per extracted record version, plus ingestion metadata.
* Additive schema drift (new columns) is applied with ``ALTER TABLE ADD COLUMN``; a manifest that
  drops a contract column is rejected (status SCHEMA_REJECTED).

DuckDB permits one writer at a time; this loader and dbt run serially (see ADR-012).
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from finance_common import contracts
from finance_common.config import local_config, repo_path
from finance_common.storage import ObjectStore, object_store_from_config, sha256_file

RAW = "finance_raw"
AUDIT = "finance_audit"


def warehouse_path() -> Path:
    return repo_path(local_config()["paths"]["warehouse_db"])


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    path = path or warehouse_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    con.execute("SET TimeZone = 'UTC'")
    for schema in (RAW, AUDIT):
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    con.execute(f"""CREATE TABLE IF NOT EXISTS {AUDIT}.raw_load_history (
        manifest_key VARCHAR PRIMARY KEY, batch_id VARCHAR, source_system VARCHAR, source_table VARCHAR,
        raw_table VARCHAR, status VARCHAR, rows_loaded BIGINT, files_loaded INTEGER, detail VARCHAR,
        loaded_at TIMESTAMPTZ, duration_ms BIGINT)""")
    return con


def raw_table_name(system: str, table: str) -> str:
    return f"{RAW}.{system}__{table}"


def _ensure_table(con: duckdb.DuckDBPyConnection, target: str, parquet: str) -> list[str]:
    exists = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema = ? AND table_name = ?",
        target.split("."),
    ).fetchall()[0][0]
    if not exists:
        con.execute(
            f"CREATE TABLE {target} AS SELECT *, CAST(NULL AS VARCHAR) AS _manifest_key, "
            f"CAST(NULL AS TIMESTAMPTZ) AS _loaded_at FROM read_parquet('{parquet}') LIMIT 0"
        )
    cols = [r[0] for r in con.execute(f"DESCRIBE {target}").fetchall()]
    incoming = con.execute(f"DESCRIBE SELECT * FROM read_parquet('{parquet}')").fetchall()
    added = []
    for name, typ, *_ in incoming:
        if name not in cols:
            con.execute(f'ALTER TABLE {target} ADD COLUMN "{name}" {typ}')
            added.append(name)
    return added


def load_manifest(con: duckdb.DuckDBPyConnection, store: ObjectStore, key: str, cache: Path) -> dict[str, Any]:
    t0 = time.perf_counter()
    manifest = json.loads(store.get_bytes(key))
    system, table = manifest["source_system"], manifest["source_table"]
    target = raw_table_name(system, table)
    contract = contracts.get(f"{system}.{table}")
    result: dict[str, Any] = {"manifest": key, "rows": 0, "status": "LOADED", "detail": ""}
    files = manifest["data_files"]
    if files:
        incoming_cols = {c["name"] for c in manifest["schema"]}
        missing = set(contract.column_names) - incoming_cols
        if missing:
            result.update(status="SCHEMA_REJECTED", detail=f"missing contract columns {sorted(missing)}")
            files = []
    local_files: list[Path] = []
    for f in files:
        local = cache / f["key"]
        store.download(f["key"], local)
        if sha256_file(local) != f["sha256"]:
            result.update(status="CHECKSUM_FAILED", detail=f"checksum mismatch for {f['key']}")
            local_files = []
            break
        local_files.append(local)
    con.execute("BEGIN TRANSACTION")
    try:
        for local in local_files:
            pq_path = local.as_posix()
            added = _ensure_table(con, target, pq_path)
            if added:
                result["detail"] += f"schema drift: added {added}; "
            con.execute(
                f"INSERT INTO {target} BY NAME SELECT *, ? AS _manifest_key, now() AS _loaded_at "
                f"FROM read_parquet('{pq_path}')",
                [key],
            )
            result["rows"] += con.execute(f"SELECT count(*) FROM read_parquet('{pq_path}')").fetchall()[0][0]
        con.execute(
            f"INSERT INTO {AUDIT}.raw_load_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                key,
                manifest["batch_id"],
                system,
                table,
                target,
                result["status"],
                result["rows"],
                len(local_files),
                result["detail"],
                datetime.now(UTC),
                int((time.perf_counter() - t0) * 1000),
            ],
        )
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    for local in local_files:
        local.unlink(missing_ok=True)
    return result


def ensure_all_raw_tables(con: duckdb.DuckDBPyConnection) -> None:
    """Create empty raw tables for contracts never delivered yet, so dbt sources always resolve."""
    from finance_common.contracts import LOGICAL_TYPES
    from ingestion.common.landing import INGESTION_COLUMNS

    duck = {
        "int": "BIGINT",
        "str": "VARCHAR",
        "date": "DATE",
        "ts": "TIMESTAMPTZ",
        "money": "DECIMAL(19,4)",
        "rate": "DECIMAL(24,10)",
        "qty": "DECIMAL(18,4)",
        "pct": "DECIMAL(9,4)",
        "bool": "BOOLEAN",
    }
    meta = {
        "_batch_id": "VARCHAR",
        "_source_system": "VARCHAR",
        "_source_table": "VARCHAR",
        "_source_file": "VARCHAR",
        "_extracted_at": "TIMESTAMPTZ",
        "_manifest_key": "VARCHAR",
        "_loaded_at": "TIMESTAMPTZ",
    }
    assert set(INGESTION_COLUMNS) <= set(meta) and set(duck) == set(LOGICAL_TYPES)
    for c in contracts.TABLES.values():
        cols = [f'"{col.name}" {duck[col.type]}' for col in c.columns] + [f"{k} {v}" for k, v in meta.items()]
        con.execute(f"CREATE TABLE IF NOT EXISTS {raw_table_name(c.system, c.name)} ({', '.join(cols)})")


def run(path: Path | None = None) -> dict[str, Any]:
    store = object_store_from_config()
    con = connect(path)
    loaded = {r[0] for r in con.execute(f"SELECT manifest_key FROM {AUDIT}.raw_load_history").fetchall()}
    pending = sorted(o.key for o in store.list("manifests/") if o.key.endswith(".json") and o.key not in loaded)
    stats: dict[str, int] = {}
    rows = 0
    cache = repo_path(local_config()["paths"]["download_cache"])
    with tempfile.TemporaryDirectory(dir=cache.parent if cache.parent.exists() else None) as tmp:
        for key in pending:
            res = load_manifest(con, store, key, Path(tmp))
            stats[res["status"]] = stats.get(res["status"], 0) + 1
            rows += res["rows"]
    ensure_all_raw_tables(con)
    sync_ingestion_metadata(con)
    con.close()
    return {"manifests_pending": len(pending), "rows_loaded": rows, "statuses": stats}


def sync_ingestion_metadata(con: duckdb.DuckDBPyConnection) -> None:
    """Copy ingestion batches and the file registry into finance_audit for pipeline-health reporting."""
    import pyarrow as pa

    from ingestion.common.state import StateStore

    state = StateStore()
    try:
        for name, rows in (("ingestion_batches", state.batches()), ("ingestion_file_registry", state.files())):
            if not rows:
                continue
            arrow_rows = pa.Table.from_pylist(rows)  # noqa: F841 - referenced by DuckDB replacement scan
            con.execute(f"CREATE OR REPLACE TABLE {AUDIT}.{name} AS SELECT * FROM arrow_rows")
    finally:
        state.close()


def main() -> None:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    print(json.dumps(run(), indent=2))


if __name__ == "__main__":
    main()
