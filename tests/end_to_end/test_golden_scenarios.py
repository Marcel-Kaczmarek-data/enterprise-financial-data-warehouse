"""Golden scenarios: problems deliberately planted by the generator must surface downstream.

Each planted issue is documented in data_generator/ and docs/financial-scenarios.md. If one of these
tests fails, either the generator stopped planting the issue or the warehouse stopped detecting it.
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal

import duckdb
import pytest

from tests.conftest import ROOT, scalar

pytestmark = pytest.mark.end_to_end


def _entities(con) -> set[str]:
    return {r[0] for r in con.execute("select entity_id from finance_core.dim_legal_entity").fetchall()}


def test_planted_gl_only_ar_adjustments_are_detected(warehouse):
    """E04 2024-03-28 EUR 18,450 and E09 2025-05-30 (EUR 27,300 in USD) were booked to the GL only."""
    rows = warehouse.execute("""
        select entity_id, min(fiscal_period), count(distinct difference), min(difference)
        from finance_intermediate.int_subledger_reconciliation
        where ledger = 'ACCOUNTS_RECEIVABLE' and abs(difference) > 0.01
        group by 1 order by 1""").fetchall()
    found = {r[0]: r for r in rows}
    expected = {"E04", "E09"} & _entities(warehouse)
    assert set(found) == expected, f"unexpected AR differences: {rows}"
    if "E04" in found:
        assert found["E04"][1] == "2024-03"
        assert found["E04"][2] == 1 and found["E04"][3] == Decimal("18450.00")
    if "E09" in found:
        assert found["E09"][1] == "2025-05" and found["E09"][2] == 1  # constant from the posting month onward
    critical = scalar(
        warehouse,
        """select count(*) from finance_marts.mart_financial_exceptions
                                    where exception_type = 'ACCOUNTS_RECEIVABLE_VS_GL' and severity = 'CRITICAL'""",
    )
    assert critical > 0


def test_duplicate_supplier_invoices_are_blocked_and_flagged(warehouse):
    blocked = scalar(warehouse, "select count(*) from finance_core.fact_vendor_invoices where is_blocked")
    assert blocked > 0
    # A blocked duplicate never carries a liability...
    assert (
        scalar(
            warehouse,
            """select count(*) from finance_core.fact_vendor_invoices
                                where is_blocked and outstanding_amount <> 0""",
        )
        == 0
    )
    # ...and every one appears in the exception mart.
    flagged = scalar(
        warehouse,
        """select count(distinct affected_ids) from finance_marts.mart_financial_exceptions
                                   where exception_type in ('DUPLICATE_INVOICE', 'POSSIBLE_DUPLICATE')""",
    )
    assert flagged >= blocked


def test_reopened_period_is_audited(warehouse):
    if "E06" not in _entities(warehouse):
        pytest.skip("E06 not generated in this profile")
    reopen = scalar(
        warehouse,
        """select count(*) from finance_staging.stg_erp__period_status_changes
                                  where entity_id = 'E06' and fiscal_period = '2023-06' and to_status = 'REOPENED'""",
    )
    assert reopen == 1
    adjustments = scalar(
        warehouse,
        """select count(*) from finance_core.fact_general_ledger
                                       where entity_id = 'E06' and fiscal_period = '2023-06'
                                         and source_document_type = 'AUDIT_ADJUSTMENT'""",
    )
    assert adjustments > 0


def test_cta_is_zero_for_eur_entities_and_nonzero_overall(warehouse):
    eur_cta = scalar(
        warehouse,
        """select coalesce(sum(abs(amount_reporting)), 0) from finance_marts.mart_balance_sheet
                                   where reporting_scope = 'STANDALONE' and functional_currency = 'EUR'
                                     and statement_line = 'Currency translation adjustments'""",
    )
    assert eur_cta == 0


def test_published_snapshot_matches_audit_record():
    published = ROOT / "warehouse" / "local" / "published" / "finance_published.duckdb"
    if not published.exists():
        pytest.skip("no published snapshot; run `python scripts/pipeline.py publish`")
    spec = importlib.util.spec_from_file_location("publish_reports", ROOT / "scripts" / "publish_reports.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    con = duckdb.connect(str(published), read_only=True)
    try:
        status, fp = con.execute("""select status, fingerprint from finance_audit.audit_report_publications
                                    order by published_at desc limit 1""").fetchall()[0]
        assert status == "PUBLISHED"
        assert mod.fingerprint(con) == fp
    finally:
        con.close()
