"""Shared fixtures. Warehouse-backed tests need a built warehouse (`python scripts/pipeline.py demo`).

When the warehouse file is missing those tests are reported as SKIPPED (never as passed).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _warehouse_file() -> Path:
    from warehouse.local.load_raw import warehouse_path

    return warehouse_path()


@pytest.fixture(scope="module")
def warehouse() -> Iterator[duckdb.DuckDBPyConnection]:
    path = _warehouse_file()
    if not path.exists():
        pytest.skip(f"warehouse not built ({path}); run `python scripts/pipeline.py demo` first")
    con = duckdb.connect(str(path), read_only=True)
    try:
        if not con.execute(
            "select count(*) from information_schema.tables where table_schema = 'finance_marts'"
        ).fetchall()[0][0]:
            pytest.skip("warehouse has no marts; run `python scripts/pipeline.py transform` first")
        yield con
    finally:
        con.close()


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    return con.execute(sql, params or []).fetchall()[0][0]
