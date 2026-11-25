"""Ingestion entry point.

    python -m ingestion.run [--sources erp,crm,files] [--tables journal_lines,...] [--file-systems banking,fx]

Exit code is non-zero when any source fails; completed sources keep their committed batches, so a
rerun resumes from the last durable watermark (safe to retry).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any

from finance_common.storage import object_store_from_config
from ingestion.common.state import StateStore


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    for noisy in ("botocore", "boto3", "urllib3", "s3transfer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sources", default="erp,crm,files")
    p.add_argument("--tables", default="")
    p.add_argument("--file-systems", default="", help="limit file ingestion, e.g. banking,fx")
    args = p.parse_args(argv)
    configure_logging()
    store = object_store_from_config()
    if hasattr(store, "ensure_bucket"):
        store.ensure_bucket()
    state = StateStore()
    summary: dict[str, Any] = {}
    failed = False
    for source in args.sources.split(","):
        t0 = time.perf_counter()
        try:
            if source == "erp":
                from ingestion.database import postgres_extract

                res = postgres_extract.run(store, state, [t for t in args.tables.split(",") if t] or None)
            elif source == "crm":
                from ingestion.api import crm_extract

                res = crm_extract.run(store, state)
            elif source == "files":
                from ingestion.files import file_ingest

                res = file_ingest.run(store, state, [s for s in args.file_systems.split(",") if s] or None)
            else:
                raise ValueError(f"unknown source {source}")
            statuses: dict[str, int] = {}
            for r in res:
                statuses[r.get("status", r.get("mode", "OK"))] = (
                    statuses.get(r.get("status", r.get("mode", "OK")), 0) + 1
                )
            summary[source] = {
                "ok": True,
                "units": len(res),
                "rows": sum(r.get("rows", 0) for r in res),
                "statuses": statuses,
                "seconds": round(time.perf_counter() - t0, 1),
            }
        except Exception as exc:
            failed = True
            logging.getLogger("ingestion").error(
                "source failed", extra={"event": {"source": source, "error": repr(exc)}}
            )
            summary[source] = {"ok": False, "error": repr(exc)[:300]}
    state.close()
    print(json.dumps(summary, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
