"""Re-running the raw load must be a no-op: every manifest is loaded exactly once (checksummed)."""

from __future__ import annotations

import duckdb
import pytest

pytestmark = pytest.mark.end_to_end


def _raw_counts(path) -> dict[str, int]:
    con = duckdb.connect(str(path), read_only=True)
    try:
        tables = [
            r[0]
            for r in con.execute("""select table_name from information_schema.tables
                                               where table_schema = 'finance_raw' order by 1""").fetchall()
        ]
        return {t: con.execute(f'select count(*) from finance_raw."{t}"').fetchall()[0][0] for t in tables}
    finally:
        con.close()


def test_second_raw_load_is_a_noop():
    from finance_common.storage import object_store_from_config
    from warehouse.local import load_raw

    path = load_raw.warehouse_path()
    if not path.exists():
        pytest.skip("warehouse not built; run `python scripts/pipeline.py demo`")
    try:
        next(iter(object_store_from_config().list("manifests/")), None)
    except Exception as exc:
        pytest.skip(f"object store not reachable ({type(exc).__name__}); run `python scripts/pipeline.py up`")
    before = _raw_counts(path)
    result = load_raw.run()
    after = _raw_counts(path)
    assert result["manifests_pending"] == 0 and result["rows_loaded"] == 0
    assert before == after
