"""Incremental PostgreSQL extraction with composite watermarks and an overlap window.

For each ERP table:
1. Read the stored watermark ``(updated_at, primary key)``.
2. Extract rows with ``updated_at >= watermark - overlap`` (full extraction when none, or for
   configured reference tables), ordered by ``(updated_at, pk)``, via server-side ``COPY``.
3. Count the same predicate in the source (source-to-target record count reconciliation).
4. Write Parquet + manifest to the landing zone, then advance the watermark (commit point).

Overlap re-reads are intentional; the warehouse deduplicates deterministically on
``(primary key, updated_at)``, which makes reprocessing idempotent.
"""

from __future__ import annotations

import io
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pyarrow as pa
import pyarrow.csv as pacsv
from psycopg import sql

from finance_common import contracts
from finance_common.config import local_config, source_config
from finance_common.storage import ObjectStore
from ingestion.common.landing import Manifest, publish_manifest, with_ingestion_columns, write_data_file
from ingestion.common.state import StateStore, Watermark

log = logging.getLogger("ingestion.erp")


def _select_list(contract: contracts.TableContract) -> str:
    parts = []
    for c in contract.columns:
        if c.type == "ts":
            parts.append(f"""to_char("{c.name}" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "{c.name}\"""")
        else:
            parts.append(f'"{c.name}"')
    return ", ".join(parts)


def _read_csv(data: bytes, contract: contracts.TableContract) -> pa.Table:
    schema = contract.arrow_schema()
    if not data.strip():
        return schema.empty_table()
    opts = pacsv.ConvertOptions(
        column_types={f.name: f.type for f in schema},
        strings_can_be_null=True,
        true_values=["t", "true"],
        false_values=["f", "false"],
        quoted_strings_can_be_null=False,
        timestamp_parsers=["%Y-%m-%dT%H:%M:%S.%fZ", pacsv.ISO8601],
    )
    table = pacsv.read_csv(io.BytesIO(data), convert_options=opts, read_options=pacsv.ReadOptions(block_size=1 << 24))
    return table.select(schema.names).cast(schema)


def extract_table(
    conn: psycopg.Connection,
    store: ObjectStore,
    state: StateStore,
    contract: contracts.TableContract,
    full: bool,
    overlap: timedelta,
) -> dict[str, Any]:
    cfg = source_config()["erp"]
    schema_name = cfg["schema"]
    wm = state.get_watermark("erp", contract.name)
    mode = "FULL" if full or wm.ts is None else "INCREMENTAL"
    batch_id = state.start_batch("erp", contract.name, mode, wm.ts)
    try:
        where: sql.Composable = sql.SQL("")
        if mode == "INCREMENTAL" and wm.ts is not None:
            lower = datetime.fromisoformat(wm.ts) - overlap
            where = sql.SQL("WHERE updated_at >= {}").format(sql.Literal(lower))
        order = ", ".join(['"updated_at"', *[f'"{k}"' for k in contract.primary_key]])
        table_sql = sql.SQL(f'{schema_name}."{contract.name}"')
        select = sql.SQL("SELECT {} FROM {} {} ORDER BY {}").format(
            sql.SQL(_select_list(contract)), table_sql, where, sql.SQL(order)
        )
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT count(*) FROM {} {}").format(table_sql, where))
            row = cur.fetchone()
            source_count = row[0] if row else 0
            buf = io.BytesIO()
            copy_sql = sql.SQL("COPY ({}) TO STDOUT WITH (FORMAT csv, HEADER true)").format(select)
            with cur.copy(copy_sql) as cp:
                for chunk in cp:
                    buf.write(chunk)
        extracted_at = datetime.now(UTC)
        table = _read_csv(buf.getvalue(), contract)
        manifest = Manifest(
            batch_id,
            "erp",
            contract.name,
            mode,
            extracted_at.isoformat(),
            source_row_count=source_count,
            watermark_from=wm.ts,
        )
        if table.num_rows != source_count:
            raise RuntimeError(f"record count mismatch: source={source_count} extracted={table.num_rows}")
        keys: list[str] = []
        max_rows = int(source_config()["defaults"]["max_rows_per_file"])
        for part, start in enumerate(range(0, max(table.num_rows, 1), max_rows)):
            chunk = with_ingestion_columns(
                table.slice(start, max_rows),
                batch_id,
                "erp",
                contract.name,
                f"postgres://{schema_name}.{contract.name}",
                extracted_at,
            )
            keys.append(write_data_file(store, manifest, chunk, part))
        new_wm = wm
        if table.num_rows:
            last = table.slice(table.num_rows - 1, 1).to_pylist()[0]
            new_wm = Watermark(last["updated_at"].isoformat(), json.dumps([str(last[k]) for k in contract.primary_key]))
        manifest.watermark_to = new_wm.ts
        publish_manifest(store, manifest)
        state.complete_batch(batch_id, "erp", contract.name, new_wm, table.num_rows, source_count, 0, keys)
        return {"table": contract.name, "mode": mode, "rows": table.num_rows, "batch_id": batch_id}
    except Exception as exc:
        state.fail_batch(batch_id, repr(exc))
        raise


def run(store: ObjectStore, state: StateStore, tables: list[str] | None = None) -> list[dict[str, Any]]:
    cfg = source_config()
    pg = local_config()["source_postgres"]
    overlap = timedelta(minutes=int(cfg["defaults"]["overlap_minutes"]))
    full_tables = set(cfg["erp"]["full_extract"])
    results = []
    with psycopg.connect(
        host=pg["host"],
        port=int(pg["port"]),
        dbname=pg["database"],
        user=pg["user"],
        password=pg["password"],
        autocommit=True,
    ) as conn:
        for contract in contracts.tables_for("erp"):
            if tables and contract.name not in tables:
                continue
            res = extract_table(conn, store, state, contract, contract.name in full_tables, overlap)
            log.info("extracted", extra={"event": res})
            results.append(res)
    return results
