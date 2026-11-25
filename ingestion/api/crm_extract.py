"""CRM REST API extraction: cursor pagination, retries with exponential backoff, incremental watermark."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pyarrow as pa
import requests

from finance_common import contracts
from finance_common.config import local_config, source_config
from finance_common.storage import ObjectStore
from ingestion.common.landing import Manifest, publish_manifest, with_ingestion_columns, write_data_file
from ingestion.common.state import StateStore, Watermark

log = logging.getLogger("ingestion.crm")
RETRYABLE = {429, 500, 502, 503, 504}


class SourceUnavailableError(RuntimeError):
    pass


def get_with_retry(
    session: requests.Session, url: str, params: dict[str, Any], retry: dict[str, Any], timeout: float, sleep=time.sleep
) -> dict[str, Any]:
    delay = float(retry["backoff_initial_seconds"])
    attempts = int(retry["max_attempts"])
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code not in RETRYABLE:
                resp.raise_for_status()
            last_error = f"HTTP {resp.status_code}"
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_error = type(exc).__name__
        if attempt < attempts:
            log.warning("retrying", extra={"event": {"url": url, "attempt": attempt, "error": last_error}})
            sleep(min(delay, float(retry["backoff_max_seconds"])))
            delay *= float(retry["backoff_multiplier"])
    raise SourceUnavailableError(f"{url} unavailable after {attempts} attempts ({last_error})")


def _to_table(records: list[dict[str, Any]], contract: contracts.TableContract) -> pa.Table:
    schema = contract.arrow_schema()
    cols: dict[str, list[Any]] = {f.name: [] for f in schema}
    for r in records:
        for f in schema:
            cols[f.name].append(r.get(f.name))
    arrays = []
    for f in schema:
        values = cols[f.name]
        if pa.types.is_timestamp(f.type):
            values = [None if v is None else datetime.fromisoformat(v) for v in values]
        elif pa.types.is_date(f.type):
            values = [None if v is None else datetime.fromisoformat(v).date() for v in values]
        elif pa.types.is_decimal(f.type):
            from decimal import Decimal

            values = [None if v is None else Decimal(v) for v in values]
        arrays.append(pa.array(values, type=f.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def run(store: ObjectStore, state: StateStore, base_url: str | None = None, sleep=time.sleep) -> list[dict[str, Any]]:
    cfg = source_config()["crm"]
    api = local_config()["crm_api"]
    base_url = base_url or api["base_url"]
    overlap = timedelta(minutes=int(source_config()["defaults"]["overlap_minutes"]))
    session = requests.Session()
    session.trust_env = False  # never route the internal CRM API through corporate proxies
    results = []
    for resource in cfg["resources"]:
        contract = contracts.get(f"crm.{resource}")
        wm = state.get_watermark("crm", resource)
        mode = "FULL" if wm.ts is None else "INCREMENTAL"
        batch_id = state.start_batch("crm", resource, mode, wm.ts)
        try:
            params: dict[str, Any] = {"page_size": api["page_size"]}
            if wm.ts:
                params["updated_since"] = (datetime.fromisoformat(wm.ts) - overlap).isoformat()
            records: list[dict[str, Any]] = []
            pages = 0
            while True:
                page = get_with_retry(
                    session, f"{base_url}/api/v1/{resource}", params, cfg["retry"], float(api["timeout_seconds"]), sleep
                )
                records += page["data"]
                pages += 1
                if not page.get("next_cursor"):
                    break
                params["cursor"] = page["next_cursor"]
            extracted_at = datetime.now(UTC)
            table = _to_table(records, contract)
            manifest = Manifest(
                batch_id,
                "crm",
                resource,
                mode,
                extracted_at.isoformat(),
                watermark_from=wm.ts,
                source_row_count=len(records),
            )
            keys = [
                write_data_file(
                    store,
                    manifest,
                    with_ingestion_columns(
                        table, batch_id, "crm", resource, f"{base_url}/api/v1/{resource}", extracted_at
                    ),
                )
            ]
            new_wm = wm
            if records:
                new_wm = Watermark(max(r["updated_at"] for r in records), None)
            manifest.watermark_to = new_wm.ts
            publish_manifest(store, manifest)
            state.complete_batch(batch_id, "crm", resource, new_wm, table.num_rows, len(records), 0, keys)
            results.append({"table": resource, "mode": mode, "rows": table.num_rows, "pages": pages})
        except Exception as exc:
            state.fail_batch(batch_id, repr(exc))
            raise
    return results
