"""Publish the simulated ERP into PostgreSQL as of a cutoff, or advance it incrementally.

    python -m source_systems.erp.seed init    --profile development --cutoff 2025-11-30T23:59:59+00:00
    python -m source_systems.erp.seed advance --to 2025-12-31T23:59:59+00:00

``init`` recreates the ERP schema from the data contracts and loads the state as of the cutoff.
``advance`` upserts every version published after the previous cutoff (new documents, status
changes, late-arriving and back-dated postings), exactly as a live ERP would have changed.
"""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime
from pathlib import Path

import psycopg

from finance_common import contracts
from finance_common.config import local_config
from source_systems.common import SourceClock, export_as_of_csv, parse_ts

SCHEMA = "erp"


def connect() -> psycopg.Connection:
    pg = local_config()["source_postgres"]
    return psycopg.connect(
        host=pg["host"],
        port=int(pg["port"]),
        dbname=pg["database"],
        user=pg["user"],
        password=pg["password"],
        autocommit=False,
    )


def create_schema(conn: psycopg.Connection, drop: bool) -> None:
    with conn.cursor() as cur:
        if drop:
            cur.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        for t in contracts.tables_for("erp"):
            cur.execute(t.postgres_ddl(SCHEMA))
            if "updated_at" in t.column_names:
                cur.execute(
                    f'CREATE INDEX IF NOT EXISTS ix_{t.name}_updated_at ON {SCHEMA}."{t.name}" '
                    f"(updated_at, {', '.join(t.primary_key)})"
                )
    conn.commit()


def load_csv(conn: psycopg.Connection, contract: contracts.TableContract, csv_path: Path, merge: bool) -> None:
    cols = contract.column_names
    col_sql = ", ".join(f'"{c}"' for c in cols)
    pk_sql = ", ".join(f'"{k}"' for k in contract.primary_key)
    target = f'{SCHEMA}."{contract.name}"'
    with conn.cursor() as cur:
        if merge:
            cur.execute(f"CREATE TEMP TABLE _stage (LIKE {target} INCLUDING DEFAULTS) ON COMMIT DROP")
        dest = "_stage" if merge else target
        with cur.copy(f"COPY {dest} ({col_sql}) FROM STDIN WITH (FORMAT csv)") as cp, csv_path.open("rb") as fh:
            while chunk := fh.read(8 << 20):
                cp.write(chunk)
        if merge:
            updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in cols if c not in contract.primary_key)
            cur.execute(
                f"INSERT INTO {target} ({col_sql}) SELECT {col_sql} FROM _stage "
                f"ON CONFLICT ({pk_sql}) DO UPDATE SET {updates}"
            )
        cur.execute(f"ANALYZE {target}")
    conn.commit()


def publish(profile: str, cutoff: datetime, since: datetime | None, drop: bool) -> dict[str, int]:
    """Initial load (drop=True) copies directly into empty tables; advance merges deltas by PK."""
    counts: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="erp_seed_") as tmp, connect() as conn:
        create_schema(conn, drop)
        for contract in contracts.tables_for("erp"):
            csv_path = Path(tmp) / f"{contract.name}.csv"
            n = export_as_of_csv(profile, contract.fqn, cutoff, since, csv_path)
            if n:
                load_csv(conn, contract, csv_path, merge=not drop)
            counts[contract.name] = n
    SourceClock().set("erp", cutoff, profile)
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--profile", default=local_config()["generator"]["default_profile"])
    i.add_argument("--cutoff", required=True)
    a = sub.add_parser("advance")
    a.add_argument("--to", required=True)
    args = p.parse_args()
    clock = SourceClock()
    if args.cmd == "init":
        counts = publish(args.profile, parse_ts(args.cutoff), None, drop=True)
    else:
        prev = clock.get("erp")
        if prev is None:
            raise SystemExit("ERP has not been initialised; run `init` first")
        profile = clock.read()["profile"]
        counts = publish(profile, parse_ts(args.to), prev, drop=False)
    total = sum(counts.values())
    print(f"ERP {args.cmd}: {total:,} rows upserted across {len(counts)} tables")
    for k, v in counts.items():
        if v:
            print(f"  {k:32s}{v:>10,}")


if __name__ == "__main__":
    main()
