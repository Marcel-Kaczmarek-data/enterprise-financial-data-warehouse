"""Publish the file- and API-based source systems as of a cutoff timestamp.

    python -m source_systems.publish_files --cutoff 2025-11-30T23:59:59+00:00 [--profile development]

Deliveries (under ``sample_data/source_drop``), each only once its period is complete at the cutoff:

* banking/statements/<bank_account>/<bank_account>_<YYYYMM>.csv   monthly statement lines
* banking/balances/balances_<YYYYMM>.json                         daily balances (bank API style)
* payroll/payroll_<YYYYMM>.csv, payroll/expense_claims_<YYYYMM>.csv
* payroll/employees_<YYYYMMDD>.csv, payroll/job_history_<YYYYMMDD>.csv   full snapshots
* budgeting/<YYYY>/budget_<entity>_<YYYY>_<version>.xlsx          one workbook per plan
* fx/rates_<YYYYMM>.csv                                            provider publications
* crm/<table>.parquet                                              backing store of the CRM REST API

Re-running with a later cutoff only adds the newly completed deliveries (existing files are kept,
just like an SFTP drop folder). ``--inject-failures`` adds a duplicate and a corrupted delivery.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from openpyxl import Workbook

from finance_common import contracts
from finance_common.config import local_config
from source_systems.common import SourceClock, parse_ts, read_as_of, source_drop_dir


def _complete_periods(cutoff: datetime, start: str) -> list[str]:
    """Calendar months whose last moment (23:59 on the final day, UTC) is at or before the cutoff."""
    out, d = [], date.fromisoformat(start).replace(day=1)
    while True:
        last_day = date(d.year + (d.month == 12), d.month % 12 + 1, 1).toordinal() - 1
        closes = datetime.combine(date.fromordinal(last_day), time(23, 59), tzinfo=UTC)
        if closes > cutoff:
            return out
        out.append(f"{d.year:04d}-{d.month:02d}")
        d = date.fromordinal(last_day + 1)


def _fmt(v: Any) -> Any:
    if isinstance(v, Decimal):
        return format(v, "f")
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return "" if v is None else v


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(columns)
        for r in rows:
            w.writerow([_fmt(r[c]) for c in columns])
    tmp.replace(path)
    return True


def publish(profile: str, cutoff: datetime, inject_failures: bool = False) -> dict[str, int]:
    drop = source_drop_dir()
    start = local_config()["generator"]["start_date"]
    periods = _complete_periods(cutoff, start)
    stats: dict[str, int] = {}

    def bump(k: str, ok: bool) -> None:
        stats[k] = stats.get(k, 0) + (1 if ok else 0)

    # ---- Banking: statements per account and month; balances per month (JSON API style)
    bt = read_as_of(profile, "banking.bank_transactions", cutoff, latest_only=False).to_pylist()
    bal = read_as_of(profile, "banking.account_balances", cutoff).to_pylist()
    cols = contracts.get("banking.bank_transactions").column_names
    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in bt:
        by_key.setdefault((r["bank_account_id"], r["value_date"].strftime("%Y-%m")), []).append(r)
    for (ba, p), rows in sorted(by_key.items()):
        if p in periods:
            rows.sort(key=lambda r: (r["value_date"], r["bank_transaction_id"]))
            bump(
                "bank_statements",
                _write_csv(drop / "banking" / "statements" / ba / f"{ba}_{p.replace('-', '')}.csv", rows, cols),
            )
    bal_by_p: dict[str, list[dict]] = {}
    for r in bal:
        bal_by_p.setdefault(r["balance_date"].strftime("%Y-%m"), []).append(r)
    for p, rows in sorted(bal_by_p.items()):
        path = drop / "banking" / "balances" / f"balances_{p.replace('-', '')}.json"
        if p in periods and not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "provider": "Northgate Commercial Bank Open API (simulated)",
                "period": p,
                "generated_at": cutoff.isoformat(),
                "data": [{k: _fmt(v) for k, v in r.items()} for r in rows],
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            bump("bank_balance_files", True)

    # ---- Payroll
    for fqn, prefix, period_col in [
        ("payroll.payroll_transactions", "payroll", "pay_period"),
        ("payroll.expense_claims", "expense_claims", "claim_date"),
    ]:
        rows = read_as_of(profile, fqn, cutoff).to_pylist()
        cols = contracts.get(fqn).column_names
        grouped: dict[str, list[dict]] = {}
        for r in rows:
            v = r[period_col]
            grouped.setdefault(v if isinstance(v, str) else v.strftime("%Y-%m"), []).append(r)
        for p, rs in sorted(grouped.items()):
            if p in periods:
                bump(prefix, _write_csv(drop / "payroll" / f"{prefix}_{p.replace('-', '')}.csv", rs, cols))
    snap = cutoff.strftime("%Y%m%d")
    for fqn, name in [("payroll.employees", "employees"), ("payroll.employee_job_history", "job_history")]:
        rows = read_as_of(profile, fqn, cutoff).to_pylist()
        bump(name, _write_csv(drop / "payroll" / f"{name}_{snap}.csv", rows, contracts.get(fqn).column_names))

    # ---- Budgeting: one workbook per entity / year / version (approved or submitted by cutoff)
    plans = read_as_of(profile, "budgeting.budget_plans", cutoff).to_pylist()
    cols = contracts.get("budgeting.budget_plans").column_names
    books: dict[tuple[str, int, str], list[dict]] = {}
    for r in plans:
        books.setdefault((r["entity_id"], r["fiscal_year"], r["budget_version"]), []).append(r)
    for (eid, year, version), rows in sorted(books.items()):
        path = drop / "budgeting" / str(year) / f"budget_{eid}_{year}_{version}.xlsx"
        if path.exists() and version != "FORECAST":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook(write_only=True)
        info = wb.create_sheet("README")
        info.append(["Halcyon Group planning system export (synthetic)"])
        info.append(["entity_id", eid])
        info.append(["fiscal_year", year])
        info.append(["budget_version", version])
        info.append(["sign convention", "positive amounts in natural presentation (revenue and cost positive)"])
        ws = wb.create_sheet("plan_lines")
        ws.append(cols)
        for r in sorted(
            rows, key=lambda x: (x["fiscal_period"], x["account_code"], x["cost_center_id"], x["scenario"])
        ):
            ws.append([_fmt(r[c]) if isinstance(r[c], (Decimal, datetime, date)) else r[c] for c in cols])
        tmp = path.with_suffix(".part")
        wb.save(tmp)
        tmp.replace(path)
        bump("budget_workbooks", True)

    # ---- FX provider publications
    rates = read_as_of(profile, "fx.exchange_rates", cutoff, latest_only=False).to_pylist()
    cols = contracts.get("fx.exchange_rates").column_names
    by_p: dict[str, list[dict]] = {}
    for r in rates:
        by_p.setdefault(r["publication_timestamp"].strftime("%Y-%m"), []).append(r)
    for p, rs in sorted(by_p.items()):
        if p in periods or p < periods[0]:
            rs.sort(key=lambda r: (r["publication_timestamp"], r["target_currency"], r["rate_type"]))
            bump("fx_files", _write_csv(drop / "fx" / f"rates_{p.replace('-', '')}.csv", rs, cols))

    # ---- CRM backing store for the REST API (all versions visible at the cutoff)
    for t in contracts.tables_for("crm"):
        table = read_as_of(profile, t.fqn, cutoff, latest_only=False)
        out = drop / "crm" / f"{t.name}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, out)
        bump("crm_tables", True)

    if inject_failures:
        _inject_failures(drop, periods)
        stats["injected_failures"] = 2
    for system in ("banking", "payroll", "budgeting", "fx", "crm"):
        SourceClock().set(system, cutoff, profile)
    return stats


def _inject_failures(drop: Path, periods: list[str]) -> None:
    """Duplicate delivery (same bytes, new name) and a truncated, corrupted statement file."""
    p = periods[-1].replace("-", "")
    stmts = sorted((drop / "banking" / "statements").rglob(f"*_{p}.csv"))
    if stmts:
        src = stmts[0]
        (src.parent / f"{src.stem}_resend.csv").write_bytes(src.read_bytes())
        data = stmts[-1].read_bytes()
        (stmts[-1].parent / f"{stmts[-1].stem}_corrupted.csv").write_bytes(data[: len(data) // 3] + b'\n"unterminated')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--inject-failures", action="store_true")
    args = parser.parse_args()
    profile = args.profile or SourceClock().read().get("profile") or local_config()["generator"]["default_profile"]
    stats = publish(profile, parse_ts(args.cutoff), args.inject_failures)
    print(json.dumps({"profile": profile, "cutoff": args.cutoff, "new_deliveries": stats}, indent=2))


if __name__ == "__main__":
    main()
