"""Shared helpers for the simulated source systems.

The generator writes the full version history of every source table. A source system "as of" a
cutoff timestamp shows, per primary key, the latest version visible at that time. Advancing the
cutoff applies later versions, which is how incremental extraction scenarios are produced.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from finance_common import contracts
from finance_common.config import local_config, repo_path


def generated_dir(profile: str) -> Path:
    return repo_path(local_config()["paths"]["generated_data"]) / profile


def source_drop_dir() -> Path:
    return repo_path(local_config()["paths"]["source_drop"])


def visibility_column(contract: contracts.TableContract) -> str:
    return "updated_at" if "updated_at" in contract.column_names else "publication_timestamp"


def parse_ts(value: str) -> datetime:
    ts = datetime.fromisoformat(value)
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _as_of_sql(profile: str, fqn: str, since: datetime | None, latest_only: bool) -> str:
    contract = contracts.get(fqn)
    path = generated_dir(profile) / contract.system / contract.name
    vis = visibility_column(contract)
    pk = ", ".join(f'"{k}"' for k in contract.primary_key)
    cols = ", ".join(f'"{c}"' for c in contract.column_names)
    where = [f'"{vis}" <= $cutoff'] + ([f'"{vis}" > $since'] if since is not None else [])
    sql = f"SELECT {cols} FROM read_parquet('{path.as_posix()}/*.parquet') WHERE {' AND '.join(where)}"
    if latest_only:
        sql += f' QUALIFY row_number() OVER (PARTITION BY {pk} ORDER BY "{vis}" DESC) = 1'
    return sql


def export_as_of_csv(profile: str, fqn: str, cutoff: datetime, since: datetime | None, target: Path) -> int:
    """Write the as-of state to a header-less CSV (fast, multi-threaded DuckDB writer)."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    params: dict[str, Any] = {"cutoff": cutoff} | ({"since": since} if since is not None else {})
    sql = _as_of_sql(profile, fqn, since, latest_only=True)
    n = con.sql(f"SELECT count(*) FROM ({sql})", params=params).fetchall()[0][0]
    target.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"COPY ({sql}) TO '{target.as_posix()}' (FORMAT csv, HEADER false)", params)
    con.close()
    return int(n)


def read_as_of(
    profile: str, fqn: str, cutoff: datetime, since: datetime | None = None, latest_only: bool = True
) -> pa.Table:
    """Rows of ``fqn`` visible at ``cutoff`` (optionally only versions after ``since``)."""
    contract = contracts.get(fqn)
    path = generated_dir(profile) / contract.system / contract.name
    vis = visibility_column(contract)
    pk = ", ".join(f'"{k}"' for k in contract.primary_key)
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    where = [f'"{vis}" <= $cutoff']
    params: dict[str, Any] = {"cutoff": cutoff}
    if since is not None:
        where.append(f'"{vis}" > $since')
        params["since"] = since
    sql = f"SELECT * FROM read_parquet('{path.as_posix()}/*.parquet') WHERE {' AND '.join(where)}"
    if latest_only:
        sql += f' QUALIFY row_number() OVER (PARTITION BY {pk} ORDER BY "{vis}" DESC) = 1'
    table = con.sql(sql, params=params).to_arrow_table()
    con.close()
    return table.cast(contract.arrow_schema())


class SourceClock:
    """Persistent record of the cutoff each source system has been published up to."""

    def __init__(self) -> None:
        self.path = source_drop_dir() / "_source_clock.json"

    def read(self) -> dict[str, str]:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def get(self, system: str) -> datetime | None:
        v = self.read().get(system)
        return parse_ts(v) if v else None

    def set(self, system: str, cutoff: datetime, profile: str) -> None:
        state = self.read()
        state[system] = cutoff.isoformat()
        state["profile"] = profile
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, indent=2), encoding="utf-8")
