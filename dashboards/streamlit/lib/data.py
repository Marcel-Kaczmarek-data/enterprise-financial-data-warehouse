"""Read-only access to the PUBLISHED warehouse snapshot.

The dashboard never opens the working warehouse (which dbt writes). It reads the snapshot that the
publication gate copies atomically after all critical checks pass, so users only ever see
validated numbers and there is no reader/writer contention on the DuckDB file.
"""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SNAPSHOT = ROOT / "warehouse" / "local" / "published" / "finance_published.duckdb"


def snapshot_path() -> Path:
    return Path(os.environ.get("FDW_PUBLISHED_PATH", str(DEFAULT_SNAPSHOT)))


def snapshot_version() -> float:
    p = snapshot_path()
    return p.stat().st_mtime if p.exists() else 0.0


@st.cache_data(show_spinner="Loading from the published warehouse snapshot...", ttl=3600)
def _query(sql: str, params: tuple, version: float) -> pd.DataFrame:
    con = duckdb.connect(str(snapshot_path()), read_only=True)
    try:
        con.execute("set TimeZone = 'UTC'")  # deterministic display, independent of the host timezone
        df = con.execute(sql, list(params)).df()
    finally:
        con.close()
    # Decimal -> float for plotting/display only; all financial arithmetic happened in the warehouse.
    for col in df.select_dtypes(include="object").columns:
        non_null = df[col].dropna()
        if len(non_null) and isinstance(non_null.iloc[0], Decimal):
            df[col] = df[col].astype(float)
    # DATE columns arrive as midnight timestamps: show them as plain dates (no "00:00:00").
    for col in df.select_dtypes(include="datetime64").columns:
        if len(df[col].dropna()) and (df[col].dt.normalize() == df[col]).all():
            df[col] = df[col].dt.date
    return df


def q(sql: str, *params) -> pd.DataFrame:
    """Run a parameterised query against the published snapshot (cached per snapshot version)."""
    return _query(sql, tuple(params), snapshot_version())


def require_snapshot() -> None:
    if not snapshot_path().exists():
        st.error(
            "No published warehouse snapshot found. Run `python scripts/pipeline.py demo` "
            "(the publication gate creates the snapshot after all critical checks pass)."
        )
        st.stop()


@st.cache_data(ttl=3600)
def _meta(version: float) -> dict:
    con = duckdb.connect(str(snapshot_path()), read_only=True)
    try:
        pub = con.execute("""select publication_id, published_at, fingerprint, latest_period
                             from finance_audit.audit_report_publications where status = 'PUBLISHED'
                             order by published_at desc limit 1""").fetchall()
        latest_posting = con.execute("select max(posting_date) from finance_core.fact_general_ledger").fetchall()[0][0]
    finally:
        con.close()
    return {"publication": pub[0] if pub else None, "latest_posting_date": latest_posting}


def meta() -> dict:
    return _meta(snapshot_version())
