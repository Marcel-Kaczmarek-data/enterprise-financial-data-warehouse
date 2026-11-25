"""Landing-zone writer: Parquet data files + JSON manifests with checksums.

Object layout (bucket ``finance-data-lake``)::

    landing/<source>/<table>/extract_date=YYYY-MM-DD/batch_id=<id>/part-00000.parquet
    manifests/<source>/<table>/<batch_id>.json
    raw/<source>/<YYYY>/<MM>/<original file name>         original files preserved for audit
    quarantine/<source>/<table>/<batch_id>/...            rejected rows / corrupted files
    audit/ingestion_runs/<YYYY-MM-DD>/<batch_id>.json

The manifest is written LAST. A batch without a manifest is incomplete and never loaded.
"""

from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from finance_common.storage import ObjectStore, sha256_bytes

INGESTION_COLUMNS = {
    "_batch_id": pa.string(),
    "_source_system": pa.string(),
    "_source_table": pa.string(),
    "_source_file": pa.string(),
    "_extracted_at": pa.timestamp("us", tz="UTC"),
}


@dataclass
class Manifest:
    batch_id: str
    source_system: str
    source_table: str
    extraction_mode: str
    extracted_at: str
    data_files: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    source_row_count: int | None = None
    watermark_from: str | None = None
    watermark_to: str | None = None
    schema: list[dict[str, str]] = field(default_factory=list)
    source_files: list[dict[str, Any]] = field(default_factory=list)
    quarantine_files: list[dict[str, Any]] = field(default_factory=list)
    manifest_version: int = 1

    def key(self) -> str:
        return f"manifests/{self.source_system}/{self.source_table}/{self.batch_id}.json"


def with_ingestion_columns(
    table: pa.Table, batch_id: str, source: str, name: str, source_file: str, extracted_at: datetime
) -> pa.Table:
    n = table.num_rows
    values = {
        "_batch_id": batch_id,
        "_source_system": source,
        "_source_table": name,
        "_source_file": source_file,
        "_extracted_at": extracted_at,
    }
    for col, typ in INGESTION_COLUMNS.items():
        table = table.append_column(pa.field(col, typ), pa.array([values[col]] * n, type=typ))
    return table


def parquet_bytes(table: pa.Table) -> bytes:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd", row_group_size=128_000)
    return buf.getvalue()


def write_data_file(store: ObjectStore, manifest: Manifest, table: pa.Table, part: int = 0) -> str:
    extract_date = manifest.extracted_at[:10]
    key = (
        f"landing/{manifest.source_system}/{manifest.source_table}/extract_date={extract_date}/"
        f"batch_id={manifest.batch_id}/part-{part:05d}.parquet"
    )
    data = parquet_bytes(table)
    store.put_bytes(key, data, {"batch-id": manifest.batch_id, "sha256": sha256_bytes(data)})
    manifest.data_files.append({"key": key, "rows": table.num_rows, "bytes": len(data), "sha256": sha256_bytes(data)})
    manifest.row_count += table.num_rows
    if not manifest.schema:
        manifest.schema = [{"name": f.name, "type": str(f.type)} for f in table.schema]
    return key


def write_quarantine(store: ObjectStore, manifest: Manifest, name: str, data: bytes, reason: str, rows: int) -> str:
    key = f"quarantine/{manifest.source_system}/{manifest.source_table}/{manifest.batch_id}/{name}"
    store.put_bytes(key, data, {"batch-id": manifest.batch_id, "reason": reason[:200]})
    manifest.quarantine_files.append({"key": key, "reason": reason, "rows": rows, "sha256": sha256_bytes(data)})
    return key


def publish_manifest(store: ObjectStore, manifest: Manifest) -> str:
    """Write the manifest (commit point of the batch) and an audit record."""
    body = json.dumps(asdict(manifest), indent=2, default=str).encode()
    store.put_bytes(manifest.key(), body, {"batch-id": manifest.batch_id})
    audit = {
        "batch_id": manifest.batch_id,
        "source_system": manifest.source_system,
        "source_table": manifest.source_table,
        "row_count": manifest.row_count,
        "source_row_count": manifest.source_row_count,
        "published_at": datetime.now(UTC).isoformat(),
        "manifest_key": manifest.key(),
        "manifest_sha256": sha256_bytes(body),
    }
    store.put_bytes(
        f"audit/ingestion_runs/{manifest.extracted_at[:10]}/{manifest.batch_id}.json", json.dumps(audit).encode()
    )
    return manifest.key()
