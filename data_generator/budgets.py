"""Budgets and forecasts (budgeting system) plus CRM pipeline snapshots.

Budget construction (documented simplification):
* ORIGINAL / BASE for year Y = actual(Y-1, same month, account, cost center) x planned growth x noise.
  For the first simulated year (no prior actuals) the base is actual(Y) x noise - flagged in docs.
* ORIGINAL / BEST and WORST: revenue +/-8 %, costs -/+4 % around BASE.
* REVISED / BASE (approved 10 July): H1 = ORIGINAL; H2 = ORIGINAL x (H1 actual / H1 budget) per account.
* FORECAST / BASE (rolling, refreshed monthly): trailing three-month actual average x seasonality.

Amounts use natural presentation: positive revenue and positive expense, in functional currency.
Grain: entity x fiscal period x group account x cost center x version x scenario.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import add_months, at, period_of, rng_for
from data_generator.invoices import SEASONALITY
from finance_common.money import ZERO, round_money

EXCLUDED = {"8200", "8350", "9000"}  # FX, disposals and income tax are not budgeted


def build_budgets(ctx: Any) -> None:
    actual: dict[tuple[str, str, str, str], Decimal] = defaultdict(lambda: ZERO)
    for (eid, period, code, cc), f in ctx.ledger.pl_by_key.items():
        if code in EXCLUDED or code in ("4500", "6650"):
            continue
        natural = -f if code[0] == "4" or code in ("8000", "8300") else f
        actual[(eid, period, code, cc or ctx.org.cc(eid, "D17"))] += natural
    years = sorted({m.year for m in ctx.months})
    keys_by_year: dict[int, set[tuple[str, str, str]]] = defaultdict(set)
    for (eid, period, code, cc) in actual:
        keys_by_year[int(period[:4])].add((eid, code, cc))
    budget_no = 0
    for y in years:
        rng = rng_for(ctx.seed, "budget", y)
        base_year = y - 1 if y - 1 in years else y
        keys = keys_by_year[base_year] | keys_by_year[y]
        approved_orig = at(date(y - 1, 12, 15), 16)
        approved_rev = at(date(y, 7, 10), 16)
        for eid, code, cc in sorted(keys):
            fc = ctx.entities[eid].functional_currency
            is_rev = code[0] == "4" or code in ("8000", "8300")
            growth = Decimal("1.08") if is_rev else Decimal("1.05")
            if base_year == y:
                growth = Decimal(1)
            dept = ctx.org.cost_center_department[cc]
            orig: dict[int, Decimal] = {}
            for m in range(1, 13):
                base = actual.get((eid, f"{base_year}-{m:02d}", code, cc), ZERO)
                orig[m] = round_money(base * growth * Decimal(repr(rng.uniform(0.94, 1.07))), fc)
            h1_act = sum((actual.get((eid, f"{y}-{m:02d}", code, cc), ZERO) for m in range(1, 7)), ZERO)
            h1_bud = sum((orig[m] for m in range(1, 7)), ZERO)
            ratio = (h1_act / h1_bud) if h1_bud else Decimal(1)
            ratio = max(Decimal("0.7"), min(Decimal("1.3"), ratio))

            def emit(m: int, version: str, scenario: str, amount: Decimal, approved, status="APPROVED") -> None:
                nonlocal budget_no
                if amount == 0:
                    return
                budget_no += 1
                ctx.sink.emit("budgeting.budget_plans", {
                    "budget_id": f"B{budget_no:09d}", "entity_id": eid, "fiscal_year": y,
                    "fiscal_period": f"{y}-{m:02d}", "account_code": code, "department_id": dept,
                    "cost_center_id": cc, "budget_version": version, "scenario": scenario,
                    "budget_amount": amount, "currency": fc, "approval_status": status, "approved_at": approved,
                    "created_at": approved - timedelta(days=20), "updated_at": approved,
                })

            for m in range(1, 13):
                emit(m, "ORIGINAL", "BASE", orig[m], approved_orig)
                up = Decimal("1.08") if is_rev else Decimal("0.96")
                down = Decimal("0.92") if is_rev else Decimal("1.04")
                emit(m, "ORIGINAL", "BEST", round_money(orig[m] * up, fc), approved_orig)
                emit(m, "ORIGINAL", "WORST", round_money(orig[m] * down, fc), approved_orig)
                if date(y, 7, 10) <= ctx.end:
                    emit(m, "REVISED", "BASE", orig[m] if m <= 6 else round_money(orig[m] * ratio, fc), approved_rev)
                month = date(y, m, 1)
                trailing = [actual.get((eid, period_of(add_months(month, -k)), code, cc), ZERO) for k in (1, 2, 3)]
                if add_months(month, -1) >= ctx.start and add_months(month, -1) <= ctx.end:
                    avg = sum(trailing, ZERO) / 3
                    prev_season = sum(Decimal(repr(SEASONALITY[(m - 1 - k) % 12])) for k in (1, 2, 3)) / 3
                    fc_amt = round_money(avg * Decimal(repr(SEASONALITY[m - 1])) / prev_season, fc) if is_rev else \
                        round_money(avg, fc)
                    emit(m, "FORECAST", "BASE", fc_amt, at(add_months(month, -1), 9), "SUBMITTED")


def build_revenue_forecasts(ctx: Any) -> None:
    """Monthly weighted-pipeline snapshots from CRM opportunities (functional currency)."""
    probability = {"PROSPECTING": Decimal("0.10"), "QUALIFICATION": Decimal("0.25"), "PROPOSAL": Decimal("0.50"),
                   "NEGOTIATION": Decimal("0.75")}
    by_entity: dict[str, list[tuple]] = defaultdict(list)
    for opp in ctx.opportunities:
        by_entity[opp[0]].append(opp)
    fid = 0
    for eid, opps in sorted(by_entity.items()):
        fc = ctx.entities[eid].functional_currency
        for m in ctx.months:
            pipeline, weighted = ZERO, ZERO
            for _, created, closed, amount, ccy in opps:
                if created <= m < closed:
                    age = (m - created).days / max(1, (closed - created).days)
                    stage = "PROSPECTING" if age < 0.25 else "QUALIFICATION" if age < 0.5 else \
                        "PROPOSAL" if age < 0.75 else "NEGOTIATION"
                    amt = round_money(amount * ctx.fx.spot(m, ccy, fc), fc)
                    pipeline += amt
                    weighted += round_money(amt * probability[stage], fc)
            fid += 1
            ctx.sink.emit("crm.revenue_forecasts", {
                "forecast_id": fid, "entity_id": eid, "forecast_month": period_of(add_months(m, 1)),
                "snapshot_date": m, "currency": fc, "pipeline_amount": pipeline, "weighted_amount": weighted,
                "created_at": at(m, 6), "updated_at": at(m, 6),
            })
