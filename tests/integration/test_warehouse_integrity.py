"""Accounting integrity of the built warehouse (runs after ingest -> load -> dbt build)."""

from __future__ import annotations

import pytest

from tests.conftest import scalar

pytestmark = pytest.mark.integration


def test_every_posted_journal_balances(warehouse):
    unbalanced = scalar(
        warehouse,
        """
        select count(*) from (
            select journal_id from finance_core.fact_general_ledger
            group by journal_id having abs(sum(signed_amount_functional)) > 0.005)""",
    )
    assert unbalanced == 0


def test_trial_balance_is_zero_per_entity_and_period(warehouse):
    off = scalar(
        warehouse,
        """
        select count(*) from (
            select entity_id, fiscal_period from finance_core.fact_general_ledger
            group by 1, 2 having abs(sum(signed_amount_functional)) > 0.005)""",
    )
    assert off == 0


def test_balance_sheet_equation_holds_everywhere(warehouse):
    worst = scalar(
        warehouse,
        """
        select coalesce(max(abs(accounting_equation_difference)), 0) from finance_marts.mart_balance_sheet""",
    )
    assert worst <= 0.01


def test_consolidation_does_not_change_group_net_profit(warehouse):
    # Eliminations reclassify inside the P&L; they must not create or destroy group profit.
    diff = scalar(
        warehouse,
        """
        with p as (
            select fiscal_period, reporting_scope, sum(amount_reporting) as net
            from finance_marts.mart_profit_and_loss
            where statement_line = 'Net profit' and (reporting_scope = 'CONSOLIDATED' or entity_id <> 'GROUP')
            group by 1, 2)
        select coalesce(max(abs(c.net - s.net)), 0)
        from p as c join p as s on c.fiscal_period = s.fiscal_period
        where c.reporting_scope = 'CONSOLIDATED' and s.reporting_scope = 'STANDALONE'""",
    )
    assert diff <= 1.0  # cent rounding across 15 entities after translation


def test_accounts_payable_subledger_ties_to_gl_every_month(warehouse):
    off = scalar(
        warehouse,
        """
        select count(*) from finance_intermediate.int_subledger_reconciliation
        where ledger = 'ACCOUNTS_PAYABLE' and abs(difference) > 0.01""",
    )
    assert off == 0


def test_bank_reconciliation_match_rate(warehouse):
    rate = scalar(
        warehouse,
        """
        select avg(case when match_status = 'MATCHED' then 1.0 else 0.0 end)
        from finance_intermediate.int_bank_transaction_matching where item_side = 'BANK'""",
    )
    assert rate >= 0.99


def test_no_postings_in_closed_periods_without_reopen(warehouse):
    # dbt stores the singular test's failing rows (store_failures); zero rows = every posting authorised.
    rows = scalar(
        warehouse, "select count(*) from finance_test_failures.assert_no_unauthorised_postings_in_closed_periods"
    )
    assert rows == 0


def test_reporting_currency_is_eur_and_rates_present(warehouse):
    missing = scalar(
        warehouse,
        """
        select count(*) from finance_core.fact_general_ledger
        where signed_amount_reporting is null or reporting_currency <> 'EUR'""",
    )
    assert missing == 0
