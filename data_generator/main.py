"""Synthetic enterprise financial data generator - orchestration.

Usage:  python -m data_generator.main --profile small [--out sample_data/generated/small]

The simulation runs month by month in business-calendar order; every financial event is posted
through the balancing :class:`~data_generator.core.Ledger`. Output: typed Parquet per source table
(mutable tables as versions), plus ``generation_manifest.json`` with counts and timings.
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from data_generator import budgets, closing
from data_generator.chart_of_accounts import build_chart_of_accounts
from data_generator.core import UTC, Ids, Ledger, PeriodCalendar, Sink, at, months_between, rng_for
from data_generator.customers import build_customers, build_intercompany_customer_accounts
from data_generator.exchange_rates import FxEngine
from data_generator.fixed_assets import FixedAssets
from data_generator.intercompany import Intercompany, ic_relationships
from data_generator.invoices import OrderToCash
from data_generator.journal_entries import REOPEN_WINDOWS, RecordToReport
from data_generator.payroll import Payroll
from data_generator.procurement import ProcureToPay
from data_generator.subsidiaries import DEPARTMENTS, ENTITIES, build_org, legal_entity_rows
from data_generator.treasury import Treasury
from data_generator.vendors import build_intercompany_vendors, build_vendors
from finance_common.config import financial_rules, local_config, repo_path
from finance_common.money import ZERO, round_money

REVENUE_PER_EMPLOYEE_EUR = Decimal("230000")
COST_DRIVER_PER_HEAD_EUR = Decimal("18300")  # monthly cost driver per employee (opex sizing)


class Context:
    def __init__(self, seed: int, start: date, end: date, profile: dict[str, Any], out_dir: Path) -> None:
        rules = financial_rules()
        self.seed, self.start, self.end, self.profile = seed, start, end, profile
        self.sink = Sink(out_dir)
        self.ids = Ids()
        self.rng_misc = rng_for(seed, "misc")
        self.fx = FxEngine(seed, start, end)
        windows = {
            (eid, p): (at(date.fromisoformat(o), 9), at(date.fromisoformat(c), 18)) for eid, p, o, c in REOPEN_WINDOWS
        }
        self.periods = PeriodCalendar(end, windows)
        self.entity_list = ENTITIES
        self.entities = {e.entity_id: e for e in ENTITIES}
        self.months = months_between(start, end)
        self.dept_area = {d: a for d, _, a in DEPARTMENTS}
        self.vat_rates = {k: Decimal(v) for k, v in rules["vat_rates"].items()}
        self.employer_rates = {k: Decimal(v) for k, v in rules["employer_contribution_rates"].items()}
        self.withholding_rate = Decimal(rules["employee_withholding_rate"])
        self.income_tax_rate = Decimal(rules["income_tax_rate"])
        self.inventory_consumed: dict[str, Decimal] = defaultdict(lambda: ZERO)
        self.inventory_consumed_last: dict[str, Decimal] = {}
        self.scheduled: list[tuple] = []
        self.vat_due: list[tuple] = []
        self.opportunities: list[tuple] = []
        self._driver_cache: dict[tuple[str, date], Decimal] = {}
        self.ledger = Ledger(self)

    # ------------------------------------------------------------------------------ helpers
    def cost_driver_eur(self, eid: str, month: date) -> Decimal:
        key = (eid, date(month.year, month.month, 1))
        if key not in self._driver_cache:
            heads = max(3, len(self.payroll.active(eid, key[1])))
            self._driver_cache[key] = COST_DRIVER_PER_HEAD_EUR * heads
        return self._driver_cache[key]

    def sales_growth_index(self, month: date) -> float:
        """Sales volume grows with commercial headcount plus a modest productivity gain."""
        from data_generator.invoices import PRODUCTIVITY_GROWTH

        heads = sum(len(self.payroll.active(e.entity_id, month)) for e in self.entity_list
                    if e.entity_type == "OPERATING")
        if not hasattr(self, "_initial_heads"):
            self._initial_heads = max(1, heads)
        years = (month - self.start).days / 365.25
        return heads / self._initial_heads * (1 + PRODUCTIVITY_GROWTH) ** years

    def employee_in_cc(self, cc: str, rng) -> int | None:
        emps = self.payroll.by_cc.get(cc)
        return rng.choice(emps).employee_id if emps else None

    def tax_txn(self, eid: str, d: date, direction: str, doc_type: str, doc_id: int, taxable: Decimal,
                rate: Decimal, tax: Decimal, ccy: str, functional: Decimal) -> None:
        self.sink.emit("erp.tax_transactions", {
            "tax_transaction_id": self.ids.next("tax"), "entity_id": eid, "tax_date": d, "tax_type": "VAT",
            "tax_direction": direction, "source_document_type": doc_type, "source_document_id": doc_id,
            "taxable_amount": taxable, "tax_rate_pct": rate, "tax_amount": tax, "currency": ccy,
            "functional_tax_amount": functional, "created_at": at(d, 20), "updated_at": at(d, 20),
        })

    def crm_opportunity(self, opp_id: int, cust: Any, eid: str, name: str, amount: Decimal, ccy: str,
                        created: date, close: date, won: bool) -> None:
        base = {"opportunity_id": opp_id, "customer_id": cust.customer_id, "entity_id": eid, "opportunity_name": name,
                "amount": amount, "currency": ccy, "expected_close_date": close}
        self.sink.emit("crm.opportunities", dict(base, stage="PROSPECTING", probability_pct=Decimal(10),
                                                 closed_date=None, is_won=None, created_at=at(created, 9),
                                                 updated_at=at(created, 9)))
        if close <= self.end:
            self.sink.emit("crm.opportunities", dict(base, stage="CLOSED_WON" if won else "CLOSED_LOST",
                                                     probability_pct=Decimal(100 if won else 0), closed_date=close,
                                                     is_won=won, created_at=at(created, 9), updated_at=at(close, 17)))
        self.opportunities.append((eid, created, close if close <= self.end else self.end + timedelta(days=1),
                                   amount, ccy))


def fridays(month_start: date, month_end_: date) -> list[date]:
    d = month_start + timedelta(days=(4 - month_start.weekday()) % 7)
    out = []
    while d <= month_end_:
        out.append(d)
        d += timedelta(days=7)
    return out


def generate(profile_name: str, out_dir: Path | None = None, seed: int | None = None,
             start: date | None = None, end: date | None = None) -> dict[str, Any]:
    cfg = local_config()["generator"]
    profile = cfg["profiles"][profile_name]
    seed = seed if seed is not None else int(cfg["seed"])
    start = start or date.fromisoformat(cfg["start_date"])
    end = end or date.fromisoformat(cfg["end_date"])
    out_dir = out_dir or repo_path(local_config()["paths"]["generated_data"]) / profile_name
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    t0 = time.perf_counter()
    ctx = Context(seed, start, end, profile, out_dir)
    org_cfg = cfg["org"]
    ctx.org = build_org(seed, start, int(org_cfg["cost_centers"]), int(org_cfg["profit_centers"]))
    ctx.treasury = Treasury(ctx)
    bank_rows = ctx.treasury.build_accounts()
    ctx.coa = build_chart_of_accounts(ENTITIES, bank_rows, start)
    ctx.assets = FixedAssets(ctx)
    ctx.payroll = Payroll(ctx)
    ctx.payroll.build_workforce(int(profile["employees"]))
    ctx.ic_relationships = ic_relationships(ENTITIES)
    customers = build_customers(ctx, int(profile["customers"]))
    ctx.ic_customer_accounts = build_intercompany_customer_accounts(ctx)
    vendors, by_entity_cat = build_vendors(ctx, int(profile["vendors"]))
    ctx.ic_vendors = build_intercompany_vendors(ctx, len(vendors) + 1000)
    ctx.o2c = OrderToCash(ctx, customers)
    ctx.p2p = ProcureToPay(ctx, by_entity_cat)
    ctx.intercompany = Intercompany(ctx)
    ctx.r2r = RecordToReport(ctx)

    # Master data
    for row in legal_entity_rows(start):
        ctx.sink.emit("erp.legal_entities", row)
    for row in ctx.org.departments:
        ctx.sink.emit("erp.departments", row)
    for row in ctx.org.cost_centers:
        ctx.sink.emit("erp.cost_centers", row)
    for row in ctx.org.profit_centers:
        ctx.sink.emit("erp.profit_centers", row)
    for row in ctx.org.products:
        ctx.sink.emit("erp.products", row)
    for row in ctx.coa.accounts:
        ctx.sink.emit("erp.accounts", row)
    for row in ctx.coa.mappings:
        ctx.sink.emit("erp.account_mappings", row)
    for rows in bank_rows.values():
        for row in rows:
            ctx.sink.emit("erp.bank_accounts", row)

    initial_heads = sum(len(ctx.payroll.active(e.entity_id, start)) for e in ENTITIES)
    ctx.o2c.calibrate(REVENUE_PER_EMPLOYEE_EUR * initial_heads, int(profile["sales_invoices_per_month"]))
    ctx.r2r.opening_balances()

    total_weight = sum(e.sales_weight for e in ENTITIES)
    for m in ctx.months:
        m_end = date(m.year, m.month, 28)
        while (m_end + timedelta(days=1)).month == m.month:
            m_end += timedelta(days=1)
        if m > start:
            ctx.payroll.workforce_month(m)
        sales_count: dict[str, int] = {}
        for e in ENTITIES:
            before = len(ctx.o2c.open)
            ctx.o2c.generate_month(e, m, int(profile["sales_invoices_per_month"]), total_weight)
            sales_count[e.entity_id] = len(ctx.o2c.open) - before
        ctx.r2r.vat_settlements(m_end)
        ctx.intercompany.charge_month(m)
        for e in ENTITIES:
            ctx.p2p.generate_month(e, m, max(2, sales_count[e.entity_id]))
        for friday in fridays(m, m_end):
            for e in ENTITIES:
                ctx.p2p.payment_run(e.entity_id, friday)
        ctx.o2c.process_until(m_end)
        for e in ENTITIES:
            ctx.payroll.run_month(e, m)
        ctx.r2r.month(m)
        ctx.r2r.annual_dividend(m)
        for e in ENTITIES:
            ctx.assets.depreciate_month(e, m)
            ctx.p2p.month_end(e, m)
            ctx.treasury.month_end(e.entity_id, m, m_end)
        if m.month % 3 == 0:
            ctx.r2r.quarter_end(m)
        ctx.inventory_consumed_last = dict(ctx.inventory_consumed)
        ctx.inventory_consumed = defaultdict(lambda: ZERO)

    ctx.payroll.finalize()
    ctx.treasury.finalize()
    closing.emit_periods(ctx)
    budgets.build_budgets(ctx)
    budgets.build_revenue_forecasts(ctx)
    for row in ctx.fx.publication_rows():
        ctx.sink.emit("fx.exchange_rates", row)
    counts = ctx.sink.close()
    elapsed = time.perf_counter() - t0

    transactional = ["erp.customer_invoices", "erp.vendor_invoices", "erp.payments", "erp.credit_notes",
                     "banking.bank_transactions", "payroll.payroll_transactions", "payroll.expense_claims",
                     "erp.purchase_orders", "erp.goods_receipts", "crm.sales_orders"]
    manifest = {
        "profile": profile_name, "seed": seed, "start_date": start.isoformat(), "end_date": end.isoformat(),
        "generated_at": datetime.now(UTC).isoformat(), "elapsed_seconds": round(elapsed, 2),
        "python": platform.python_version(), "machine": platform.machine(), "processor": platform.processor(),
        "journals_posted": ctx.ledger.journal_count, "journal_lines": ctx.ledger.line_count,
        "business_document_versions": sum(counts.get(t, 0) for t in transactional),
        "local_accounts": len(ctx.coa.accounts), "row_counts": dict(sorted(counts.items())),
        "price_scale": str(ctx.o2c.price_scale),
        "note": "Mutable source tables contain one row per version; counts are version counts.",
    }
    (out_dir / "generation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=local_config()["generator"]["default_profile"])
    parser.add_argument("--out", type=Path)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    manifest = generate(args.profile, args.out, args.seed)
    print(json.dumps({k: v for k, v in manifest.items() if k != "row_counts"}, indent=2))
    _ = round_money  # keep import for type checkers


if __name__ == "__main__":
    main()
