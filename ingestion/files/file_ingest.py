"""File ingestion (CSV, JSON, Excel) with checksum-based duplicate detection and quarantine.

Per file:
1. SHA-256 checksum. A checksum already registered as LOADED -> status DUPLICATE (skipped), even if
   the file name differs (re-sent deliveries).
2. Parse against the table contract. Files that cannot be parsed at all are quarantined whole.
3. Row-level validation: required fields, type conversion, valid currency codes, positive FX rates.
   Invalid rows go to ``quarantine/`` with a reason; valid rows land as Parquet.
4. The original file is preserved under ``raw/`` for audit; the manifest is written last.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa
from openpyxl import load_workbook

from finance_common import contracts
from finance_common.config import source_config
from finance_common.money import VALID_CURRENCIES
from finance_common.storage import ObjectStore, sha256_bytes
from ingestion.common.landing import (
    Manifest,
    parquet_bytes,
    publish_manifest,
    with_ingestion_columns,
    write_data_file,
    write_quarantine,
)
from ingestion.common.state import StateStore, Watermark
from source_systems.common import source_drop_dir

log = logging.getLogger("ingestion.files")


class CorruptFileError(ValueError):
    pass


def _parse_value(value: Any, typ: str) -> Any:
    if value is None or value == "":
        return None
    if typ == "int":
        return int(value)
    if typ in ("money", "rate", "qty", "pct"):
        try:
            return Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal: {value!r}") from exc
    if typ == "date":
        return (
            value
            if isinstance(value, date) and not isinstance(value, datetime)
            else date.fromisoformat(str(value)[:10])
        )
    if typ == "ts":
        ts = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return ts if ts.tzinfo else ts.replace(tzinfo=UTC)
    if typ == "bool":
        return str(value).lower() in ("true", "1", "t", "yes")
    return str(value)


def read_records(data: bytes, fmt: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        if fmt == "csv":
            text = data.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            rows = list(reader)
            if reader.fieldnames is None:
                raise CorruptFileError("empty CSV")
            return rows
        if fmt == "json":
            payload = json.loads(data)
            return payload[spec.get("records_path", "data")]
        if fmt == "excel":
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb[spec.get("sheet", wb.sheetnames[0])]
            it = ws.iter_rows(values_only=True)
            header = [str(h) for h in next(it)]
            return [dict(zip(header, r, strict=False)) for r in it if any(v is not None for v in r)]
    except (UnicodeDecodeError, json.JSONDecodeError, csv.Error, KeyError, StopIteration, OSError) as exc:
        raise CorruptFileError(f"{type(exc).__name__}: {exc}") from exc
    except Exception as exc:  # openpyxl raises a variety of zip/xml errors for corrupted workbooks
        raise CorruptFileError(f"{type(exc).__name__}: {exc}") from exc
    raise ValueError(f"unsupported format {fmt}")


def validate(records: list[dict[str, Any]], contract: contracts.TableContract) -> tuple[list[dict], list[dict]]:
    expected = set(contract.column_names)
    if records:
        missing = expected - set(records[0].keys())
        if missing:
            raise CorruptFileError(f"schema mismatch: missing columns {sorted(missing)}")
    good, bad = [], []
    for i, rec in enumerate(records):
        try:
            row = {c.name: _parse_value(rec.get(c.name), c.type) for c in contract.columns}
            for c in contract.columns:
                if not c.nullable and row[c.name] is None:
                    raise ValueError(f"required field {c.name} is empty")
            for ccy_col in ("currency", "source_currency", "target_currency", "salary_currency"):
                if ccy_col in row and row[ccy_col] is not None and row[ccy_col] not in VALID_CURRENCIES:
                    raise ValueError(f"invalid currency code {row[ccy_col]!r}")
            if contract.name == "exchange_rates" and row["exchange_rate"] is not None and row["exchange_rate"] <= 0:
                raise ValueError("non-positive exchange rate")
            good.append(row)
        except (ValueError, TypeError) as exc:
            bad.append({"row_number": i + 2, "reason": str(exc), **{k: str(v) for k, v in rec.items()}})
    return good, bad


def ingest_group(
    store: ObjectStore, state: StateStore, system: str, spec: dict[str, Any], paths: list[Path], drop_root: Path
) -> list[dict[str, Any]]:
    """Ingest all new files of one delivery type as a single batch (one landing file, one manifest)."""
    results: list[dict[str, Any]] = []
    candidates: list[tuple[Path, str, bytes, str]] = []
    seen_in_run: dict[str, str] = {}
    for path in paths:
        data = path.read_bytes()
        checksum = sha256_bytes(data)
        rel = path.relative_to(drop_root).as_posix()
        prior = state.file_status(checksum)
        original = prior[1] if prior else seen_in_run.get(checksum)
        if original is not None:
            if original != rel:
                if state.file_status(f"{checksum}:{rel}") is None:
                    state.register_file(
                        f"{checksum}:{rel}",
                        system,
                        rel,
                        "DUPLICATE",
                        None,
                        None,
                        0,
                        0,
                        f"identical content already received as {original}",
                    )
                    results.append({"file": rel, "status": "DUPLICATE"})
            continue
        seen_in_run[checksum] = rel
        candidates.append((path, rel, data, checksum))
    if not candidates:
        return results
    contract = contracts.get(f"{system}.{spec['table']}")
    batch_id = state.start_batch(system, spec["table"], "FILE", None)
    extracted_at = datetime.now(UTC)
    manifest = Manifest(batch_id, system, spec["table"], "FILE", extracted_at.isoformat())

    def archive(item: tuple[Path, str, bytes, str]) -> dict[str, Any]:
        _path, rel, data, checksum = item
        key = f"raw/{system}/{extracted_at:%Y/%m}/{batch_id}/{rel.replace('/', '__')}"
        store.put_bytes(key, data, {"sha256": checksum})
        return {"key": key, "original_path": rel, "sha256": checksum, "bytes": len(data)}

    with ThreadPoolExecutor(max_workers=16) as pool:
        manifest.source_files = list(pool.map(archive, candidates))
    tables: list[pa.Table] = []
    registry: list[tuple] = []
    total_records = 0
    for (path, rel, data, checksum), src in zip(candidates, manifest.source_files, strict=True):
        try:
            records = read_records(data, spec["format"], spec)
            good, bad = validate(records, contract)
        except CorruptFileError as exc:
            write_quarantine(store, manifest, rel.replace("/", "__"), data, str(exc), 0)
            registry.append((checksum, rel, "QUARANTINED", src["key"], 0, 0, str(exc)))
            results.append({"file": rel, "status": "QUARANTINED", "reason": str(exc)})
            continue
        total_records += len(records)
        if bad:
            write_quarantine(
                store,
                manifest,
                f"{path.stem}_rejected_rows.parquet",
                parquet_bytes(pa.Table.from_pylist(bad)),
                f"{len(bad)} invalid rows",
                len(bad),
            )
        t = pa.Table.from_pylist(good, schema=contract.arrow_schema())
        tables.append(with_ingestion_columns(t, batch_id, system, spec["table"], rel, extracted_at))
        registry.append((checksum, rel, "LOADED", src["key"], len(good), len(bad), ""))
        results.append({"file": rel, "status": "LOADED", "rows": len(good), "quarantined": len(bad)})
    if tables:
        write_data_file(store, manifest, pa.concat_tables(tables))
    manifest.source_row_count = total_records
    publish_manifest(store, manifest)  # commit point
    for checksum, rel, status, key, n_good, n_bad, detail in registry:
        state.register_file(checksum, system, rel, status, batch_id, key, n_good, n_bad, detail)
    state.complete_batch(
        batch_id,
        system,
        spec["table"],
        Watermark(extracted_at.isoformat(), None),
        manifest.row_count,
        total_records,
        sum(r[5] for r in registry),
        [d["key"] for d in manifest.data_files],
    )
    return results


def run(store: ObjectStore, state: StateStore, systems: list[str] | None = None) -> list[dict[str, Any]]:
    drop_root = source_drop_dir()
    results = []
    for system, specs in source_config()["files"].items():
        if systems and system not in systems:
            continue
        for spec in specs:
            paths = [p for p in sorted(drop_root.glob(spec["pattern"])) if p.suffix not in (".part", ".tmp")]
            results += ingest_group(store, state, system, spec, paths, drop_root)
    return results
