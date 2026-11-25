"""Financial publication gate: publish the reporting snapshot only when critical checks pass.

1. Reads dbt ``run_results.json`` + ``manifest.json`` and collects failed/errored nodes. Any failed
   test tagged ``critical`` (or any model error) BLOCKS publication.
2. Counts open CRITICAL items in ``mart_financial_exceptions`` (reported, and blocking only with
   ``--block-on-exceptions``: planted demo exceptions are expected and must stay visible).
3. On success, records the publication in ``finance_audit.audit_report_publications`` with a
   reproducibility fingerprint (hash of consolidated monthly net profit and total assets) and
   atomically copies the warehouse to the read-only published snapshot used by the dashboard.

Exit code 0 = published, 2 = blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from finance_common.config import local_config, repo_path  # noqa: E402

TARGET = ROOT / "dbt_finance" / "target"


def critical_failures() -> tuple[list[str], dict]:
    results = json.loads((TARGET / "run_results.json").read_text(encoding="utf-8"))
    manifest = json.loads((TARGET / "manifest.json").read_text(encoding="utf-8"))
    nodes = manifest["nodes"]
    failures, summary = [], {"pass": 0, "warn": 0, "fail": 0, "error": 0, "skipped": 0, "success": 0}
    for r in results["results"]:
        status = r["status"]
        summary[status] = summary.get(status, 0) + 1
        node = nodes.get(r["unique_id"], {})
        tags = set(node.get("tags", [])) | set(node.get("config", {}).get("tags", []))
        if status == "error" or (status == "fail" and "critical" in tags):
            failures.append(f"{r['unique_id']} ({status})")
    summary["invocation_id"] = results["metadata"]["invocation_id"]
    return failures, summary


def fingerprint(con: duckdb.DuckDBPyConnection) -> str:
    rows = con.execute("""
        select p.fiscal_period, p.amount_reporting, b.total_assets
        from finance_marts.mart_profit_and_loss as p
        join finance_marts.mart_executive_financial_summary as b
          on b.reporting_scope = 'CONSOLIDATED' and b.fiscal_period = p.fiscal_period
        where p.reporting_scope = 'CONSOLIDATED' and p.statement_line = 'Net profit'
        order by 1""").fetchall()
    return hashlib.sha256(json.dumps([[str(c) for c in r] for r in rows]).encode()).hexdigest()[:16]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--block-on-exceptions", action="store_true")
    args = p.parse_args()
    paths = local_config()["paths"]
    warehouse = repo_path(paths["warehouse_db"])
    published = repo_path(paths["published_db"])
    failures, summary = critical_failures()
    con = duckdb.connect(str(warehouse))
    con.execute("""create table if not exists finance_audit.audit_report_publications (
        publication_id varchar, published_at timestamptz, status varchar, dbt_invocation_id varchar,
        fingerprint varchar, critical_test_failures integer, open_critical_exceptions integer,
        latest_period varchar, detail varchar)""")
    open_critical = con.execute(
        "select count(*) from finance_marts.mart_financial_exceptions where severity = 'CRITICAL'"
    ).fetchall()[0][0]
    latest = con.execute("select max(fiscal_period) from finance_core.fact_general_ledger").fetchall()[0][0]
    blocked = bool(failures) or (args.block_on_exceptions and open_critical > 0)
    pub_id = f"PUB-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"
    fp = fingerprint(con) if not failures else None
    con.execute(
        "insert into finance_audit.audit_report_publications values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            pub_id,
            datetime.now(UTC),
            "BLOCKED" if blocked else "PUBLISHED",
            summary["invocation_id"],
            fp,
            len(failures),
            open_critical,
            latest,
            "; ".join(failures)[:2000],
        ],
    )
    con.close()
    report = {
        "publication_id": pub_id,
        "status": "BLOCKED" if blocked else "PUBLISHED",
        "fingerprint": fp,
        "latest_period": latest,
        "dbt_results": summary,
        "critical_test_failures": failures,
        "open_critical_exceptions": open_critical,
    }
    if not blocked:
        published.parent.mkdir(parents=True, exist_ok=True)
        tmp = published.with_suffix(".tmp")
        shutil.copyfile(warehouse, tmp)
        os.replace(tmp, published)  # atomic swap: readers never see a half-written snapshot
        report["published_snapshot"] = str(published.relative_to(ROOT))
    print(json.dumps(report, indent=2, default=str))
    return 2 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
