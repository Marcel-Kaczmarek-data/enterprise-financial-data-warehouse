"""Double-entry ledger behaviour: balancing, rounding residuals, closed periods, currency handling."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from data_generator.core import (
    Ids,
    Ledger,
    Line,
    PeriodCalendar,
    PeriodClosedError,
    UnbalancedJournalError,
    at,
    rng_for,
)


class FakeSink:
    def __init__(self) -> None:
        self.rows: dict[str, list[dict]] = {}

    def emit(self, fqn: str, row: dict) -> None:
        self.rows.setdefault(fqn, []).append(row)


class FakeCoa:
    def account_for(self, entity_id, group_code, variant=None):
        return int(group_code)


class FakeFx:
    def __init__(self, rate: Decimal) -> None:
        self.rate = rate

    def spot(self, d, source, target):
        return Decimal(1) if source == target else self.rate


def make_ctx(rate: Decimal = Decimal("0.3333333333")):
    ctx = SimpleNamespace(
        entities={"E1": SimpleNamespace(functional_currency="EUR")},
        periods=PeriodCalendar(date(2025, 12, 31)),
        rng_misc=rng_for(1, "test"),
        ids=Ids(),
        sink=FakeSink(),
        coa=FakeCoa(),
        fx=FakeFx(rate),
        org=SimpleNamespace(cost_center_department={}),
    )
    ctx.ledger = Ledger(ctx)
    return ctx


def lines_of(ctx):
    return ctx.sink.rows["erp.journal_lines"]


def test_customer_invoice_example_posts_balanced_lines():
    ctx = make_ctx()
    ctx.ledger.post(
        "E1",
        date(2025, 3, 10),
        "AR_INVOICE",
        [
            Line("1100", Decimal("1200"), "EUR"),
            Line("4100", Decimal("-1000"), "EUR"),
            Line("2200", Decimal("-200"), "EUR"),
        ],
        created_at=at(date(2025, 3, 10)),
    )
    rows = lines_of(ctx)
    assert sum(r["debit_amount"] for r in rows) == sum(r["credit_amount"] for r in rows) == Decimal("1200")
    ar = next(r for r in rows if r["account_id"] == 1100)
    assert ar["debit_amount"] == Decimal("1200") and ar["credit_amount"] == 0


def test_unbalanced_journal_is_rejected():
    ctx = make_ctx()
    with pytest.raises(UnbalancedJournalError):
        ctx.ledger.post(
            "E1",
            date(2025, 3, 10),
            "ADJUSTMENT",
            [Line("6400", Decimal("100"), "EUR"), Line("2100", Decimal("-90"), "EUR")],
            created_at=at(date(2025, 3, 10)),
        )


def test_rounding_residual_goes_to_computed_line_not_explicit_control_line():
    ctx = make_ctx(Decimal("0.3333333333"))
    # 3 x 1.00 USD at 0.333.. = 0.33 each -> residual 0.01 vs the explicit AR amount of 1.00
    ctx.ledger.post(
        "E1",
        date(2025, 3, 10),
        "AR_INVOICE",
        [
            Line("1100", Decimal("3.00"), "USD", Decimal("1.00")),
            Line("4000", Decimal("-1.00"), "USD"),
            Line("4100", Decimal("-1.00"), "USD"),
            Line("4200", Decimal("-1.00"), "USD"),
        ],
        created_at=at(date(2025, 3, 10)),
    )
    rows = lines_of(ctx)
    assert sum(r["functional_currency_amount"] for r in rows) == 0
    assert next(r for r in rows if r["account_id"] == 1100)["functional_currency_amount"] == Decimal("1.00")


def test_posting_into_closed_period_is_refused():
    ctx = make_ctx()
    with pytest.raises(PeriodClosedError):
        ctx.ledger.post(
            "E1",
            date(2025, 1, 15),
            "AP_INVOICE",
            [Line("6400", Decimal("10"), "EUR"), Line("2000", Decimal("-10"), "EUR")],
            created_at=at(date(2025, 3, 20)),
        )


def test_soft_closed_period_accepts_finance_journals_only():
    cal = PeriodCalendar(date(2025, 12, 31))
    created = at(date(2025, 2, 7), 12)  # after soft close (BD4 18:00 = 6 Feb), before close (BD8 = 12 Feb)
    assert cal.status("E1", "2025-01", created) == "SOFT_CLOSED"
    assert cal.allowed("E1", date(2025, 1, 31), created, finance_journal=True)
    assert not cal.allowed("E1", date(2025, 1, 31), created, finance_journal=False)


def test_reopened_period_window():
    cal = PeriodCalendar(date(2025, 12, 31), {("E1", "2025-01"): (at(date(2025, 4, 1), 9), at(date(2025, 4, 2), 18))})
    assert cal.status("E1", "2025-01", at(date(2025, 4, 1), 12)) == "REOPENED"
    assert cal.status("E1", "2025-01", at(date(2025, 4, 3), 12)) == "CLOSED"


def test_draft_journal_does_not_affect_running_balances():
    ctx = make_ctx()
    ctx.ledger.post(
        "E1",
        date(2025, 3, 10),
        "ADJUSTMENT",
        [Line("6400", Decimal("50"), "EUR"), Line("2100", Decimal("-50"), "EUR")],
        posting_status="DRAFT",
        created_at=at(date(2025, 3, 10)),
    )
    assert ctx.ledger.balances[("E1", "6400")] == 0
