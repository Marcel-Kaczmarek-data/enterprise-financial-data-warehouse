"""Financial invariants of the generated source data (small profile, deterministic seed).

These tests read the generator's Parquet output with DuckDB and assert accounting properties that
any downstream model relies on. They run in about 30 seconds and need no Docker services.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from data_generator.main import generate

pytestmark = pytest.mark.financial


@pytest.fixture(scope="module")
def con(tmp_path_factory) -> duckdb.DuckDBPyConnection:
    out: Path = tmp_path_factory.mktemp("gen") / "small"
    manifest = generate("small", out)
    assert manifest["journal_lines"] > 50_000
    c = duckdb.connect()

    def view(name: str, system: str) -> None:
        c.execute(f"create view {name}_v as select * from read_parquet('{(out / system / name).as_posix()}/*.parquet')")

    for n in [
        "journal_headers",
        "journal_lines",
        "account_mappings",
        "customer_invoices",
        "credit_notes",
        "payment_allocations",
        "vendor_invoices",
        "accounting_periods",
    ]:
        view(n, "erp")
    view("bank_transactions", "banking")
    for t, k in [
        ("journal_headers", "journal_id"),
        ("customer_invoices", "invoice_id"),
        ("vendor_invoices", "vendor_invoice_id"),
    ]:
        c.execute(
            f"create view {t} as select * exclude rn from (select *, row_number() over "
            f"(partition by {k} order by updated_at desc) rn from {t}_v) where rn = 1"
        )
    c.execute("""create view gl as select l.*, h.entity_id, h.journal_type, h.posting_date, m.group_account_code g
                 from journal_lines_v l join journal_headers h using (journal_id)
                 join account_mappings_v m on m.account_id = l.account_id where h.posting_status = 'POSTED'""")
    return c


def one(con, sql: str):
    return con.execute(sql).fetchall()[0][0]


def test_every_journal_balances_exactly(con):
    assert (
        one(
            con,
            "select count(*) from (select journal_id from journal_lines_v group by 1 "
            "having sum(functional_currency_amount) <> 0)",
        )
        == 0
    )


def test_debit_credit_signs_are_consistent(con):
    assert (
        one(
            con,
            "select count(*) from journal_lines_v where debit_amount < 0 or credit_amount < 0 "
            "or (debit_amount > 0 and credit_amount > 0) "
            "or debit_amount - credit_amount <> functional_currency_amount",
        )
        == 0
    )


def test_trial_balance_is_zero_for_every_entity(con):
    assert (
        one(
            con,
            "select count(*) from (select entity_id from gl group by 1 having sum(functional_currency_amount) <> 0)",
        )
        == 0
    )


def test_every_line_uses_a_mapped_account(con):
    assert (
        one(
            con,
            "select count(*) from journal_lines_v l left join account_mappings_v m using (account_id) "
            "where m.group_account_code is null",
        )
        == 0
    )


def test_fiscal_period_matches_posting_date(con):
    assert one(con, "select count(*) from journal_headers where fiscal_period <> strftime(posting_date, '%Y-%m')") == 0


def test_ar_subledger_equals_gl_except_planted_manual_adjustments(con):
    rows = con.execute("""
        with inv_f as (
            select i.entity_id, i.invoice_id, sum(l.functional_currency_amount) f
            from customer_invoices i join journal_lines_v l on l.journal_id = i.journal_id
            join account_mappings_v m on m.account_id = l.account_id
            where m.group_account_code in ('1100', '1150') group by all),
        cn as (select invoice_id, sum(functional_amount) f from credit_notes_v group by 1),
        al as (select document_id invoice_id, sum(functional_amount_relieved) f from payment_allocations_v
               where document_type = 'CUSTOMER_INVOICE' group by 1),
        rf as (select c.invoice_id, sum(a.functional_amount_relieved) f from payment_allocations_v a
               join credit_notes_v c on a.document_type = 'CREDIT_NOTE' and c.credit_note_id = a.document_id group by 1),
        sub as (select entity_id, sum(i.f - coalesce(cn.f, 0) - coalesce(al.f, 0) - coalesce(rf.f, 0)) s
                from inv_f i left join cn using (invoice_id) left join al using (invoice_id)
                left join rf using (invoice_id) group by 1),
        g as (select entity_id, sum(functional_currency_amount) b from gl where g in ('1100', '1150') group by 1)
        select entity_id, b - coalesce(s, 0) from g left join sub using (entity_id) where b - coalesce(s, 0) <> 0
        order by 1""").fetchall()
    # Exactly the two documented GL-only manual AR adjustments remain (E04 EUR, E09 USD).
    assert [r[0] for r in rows] == ["E04", "E09"]
    assert rows[0][1] == 18450


def test_ap_subledger_equals_gl_exactly(con):
    assert (
        one(
            con,
            """
        with inv_f as (
            select i.entity_id, i.vendor_invoice_id id, -sum(l.functional_currency_amount) f
            from vendor_invoices i join journal_lines_v l on l.journal_id = i.journal_id
            join account_mappings_v m on m.account_id = l.account_id
            where m.group_account_code in ('2000', '2050') group by all),
        al as (select document_id id, sum(functional_amount_relieved) f from payment_allocations_v
               where document_type = 'VENDOR_INVOICE' group by 1),
        sub as (select entity_id, sum(i.f - coalesce(al.f, 0)) s from inv_f i left join al using (id) group by 1),
        g as (select entity_id, -sum(functional_currency_amount) b from gl where g in ('2000', '2050') group by 1)
        select count(*) from g left join sub using (entity_id) where b - coalesce(s, 0) <> 0""",
        )
        == 0
    )


def test_no_payment_exceeds_its_invoice(con):
    assert (
        one(
            con,
            """
        select count(*) from (
            select a.document_id, sum(a.allocated_amount + a.discount_amount) settled, any_value(i.invoice_amount) amt
            from payment_allocations_v a join vendor_invoices i on i.vendor_invoice_id = a.document_id
            where a.document_type = 'VENDOR_INVOICE' group by 1) where settled > amt""",
        )
        == 0
    )


def test_reversals_reference_existing_journals(con):
    assert (
        one(
            con,
            "select count(*) from journal_headers r left join journal_headers o "
            "on r.reversal_of_journal_id = o.journal_id "
            "where r.reversal_of_journal_id is not null and o.journal_id is null",
        )
        == 0
    )


def test_duplicate_supplier_invoices_are_received_after_the_original(con):
    assert (
        one(
            con,
            """
        select count(*) from (
            select vendor_id, vendor_invoice_number, row_number() over (partition by vendor_id, vendor_invoice_number
                order by created_at) rn, journal_id, approval_status from vendor_invoices)
        where rn = 1 and approval_status = 'REJECTED_DUPLICATE'""",
        )
        == 0
    )


def test_generation_is_deterministic(tmp_path):
    a = generate("small", tmp_path / "a")
    b = generate("small", tmp_path / "b")
    assert a["row_counts"] == b["row_counts"]
    assert a["journal_lines"] == b["journal_lines"]
