"""Fixed asset register, straight-line depreciation and disposals.

* Acquisition (from CAPEX supplier invoices): Dr 1500 PP&E cost  Cr 2000 AP (posted by procurement)
* Monthly depreciation (full month following in-service date): Dr 7000  Cr 1590
* Disposal at end of life: Dr 1590 accumulated, Dr 1010 proceeds, Cr 1500 cost, +/- 8350 gain/loss
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import Line, add_months, at, month_end, period_of, rng_for
from finance_common.money import ZERO, round_money

ASSET_CLASSES = [("IT_EQUIPMENT", 36), ("FURNITURE", 60), ("MACHINERY", 120), ("VEHICLES", 60), ("LEASEHOLD", 84)]


@dataclass
class Asset:
    row: dict[str, Any]
    entity_id: str
    currency: str
    cost: Decimal
    life: int
    start_period: date  # first month of depreciation
    accumulated: Decimal = ZERO
    months_done: int = 0
    disposed: bool = False


class FixedAssets:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.assets: list[Asset] = []
        self.by_entity: dict[str, list[Asset]] = defaultdict(list)

    def _new(self, entity: Any, acq: date, cost: Decimal, cc: str | None, vi_id: int | None, rng,
             asset_class: tuple[str, int] | None = None) -> Asset:
        cls, life = asset_class or rng.choice(ASSET_CLASSES)
        asset_id = self.ctx.ids.next("asset")
        start = add_months(date(acq.year, acq.month, 1), 1)
        row = {
            "asset_id": asset_id, "asset_number": f"FA-{entity.entity_id}-{asset_id:06d}",
            "entity_id": entity.entity_id, "asset_class": cls, "description": f"{cls.replace('_', ' ').title()} asset",
            "acquisition_date": acq, "in_service_date": acq, "acquisition_cost": cost,
            "currency": entity.functional_currency, "useful_life_months": life, "salvage_value": ZERO,
            "depreciation_method": "STRAIGHT_LINE", "cost_center_id": cc, "vendor_invoice_id": vi_id,
            "asset_status": "ACTIVE", "disposal_date": None, "disposal_proceeds": None,
            "created_at": at(max(acq, self.ctx.start - timedelta(days=1)), 12),
            "updated_at": at(max(acq, self.ctx.start - timedelta(days=1)), 12),
        }
        a = Asset(row, entity.entity_id, entity.functional_currency, cost, life, start)
        self.assets.append(a)
        self.by_entity[entity.entity_id].append(a)
        return a

    def opening_register(self, entity: Any, total_cost: Decimal, rng) -> tuple[Decimal, Decimal]:
        """Create historical assets acquired before the start date. Returns (cost, accumulated)."""
        fc = entity.functional_currency
        n = 6 if entity.entity_type == "OPERATING" else 3
        costs = [round_money(total_cost / n * Decimal(repr(rng.uniform(0.6, 1.4))), fc) for _ in range(n)]
        acc_total = ZERO
        for c in costs:
            acq = self.ctx.start - timedelta(days=rng.randint(60, 1500))
            cc = rng.choice(self.ctx.org.entity_cost_centers[entity.entity_id])
            a = self._new(entity, acq, c, cc, None, rng)
            months = max(0, (self.ctx.start.year - a.start_period.year) * 12 + self.ctx.start.month
                         - a.start_period.month)
            months = min(months, a.life - 1)
            a.months_done = months
            a.accumulated = round_money(c * months / a.life, fc)
            acc_total += a.accumulated
            self.ctx.sink.emit("erp.fixed_assets", a.row)
        return sum(costs, ZERO), acc_total

    def register_acquisition(self, entity: Any, d: date, cost: Decimal, cc: str | None, vi_id: int, rng) -> None:
        a = self._new(entity, d, cost, cc, vi_id, rng)
        a.row["created_at"] = a.row["updated_at"] = at(d, 15)
        self.ctx.sink.emit("erp.fixed_assets", a.row)

    def depreciate_month(self, entity: Any, month_start: date) -> None:
        ctx = self.ctx
        eid, fc = entity.entity_id, entity.functional_currency
        m_end = month_end(month_start)
        per_cc: dict[str, Decimal] = defaultdict(lambda: ZERO)
        schedule_rows = []
        for a in self.by_entity[eid]:
            if a.disposed or a.start_period > month_start or a.months_done >= a.life:
                continue
            a.months_done += 1
            if a.months_done == a.life:
                dep = a.cost - a.accumulated  # final month absorbs rounding
            else:
                dep = round_money(a.cost / a.life, fc)
            a.accumulated += dep
            cc = a.row["cost_center_id"] or ctx.org.cc(eid, "D17")
            per_cc[cc] += dep
            schedule_rows.append({
                "asset_id": a.row["asset_id"], "fiscal_period": period_of(month_start), "entity_id": eid,
                "depreciation_amount": dep, "accumulated_depreciation": a.accumulated,
                "net_book_value": a.cost - a.accumulated, "journal_id": None,
                "created_at": at(m_end, 20), "updated_at": at(m_end, 20),
            })
        if per_cc:
            lines = []
            for cc, amt in sorted(per_cc.items()):
                lines += [Line("7000", amt, fc, None, cc, description="Depreciation"),
                          Line("1590", -amt, fc, None, cc, description="Accumulated depreciation")]
            jid = ctx.ledger.post(eid, m_end, "DEPRECIATION", lines, source_document_type="DEPRECIATION_RUN",
                                  source_document_id=f"DEP-{eid}-{period_of(month_start)}",
                                  reference_number=f"DEP-{eid}-{period_of(month_start)}",
                                  description="Monthly depreciation run", created_at=at(m_end, 20),
                                  created_by="close.automation")
            for r in schedule_rows:
                r["journal_id"] = jid
                ctx.sink.emit("erp.depreciation_schedule", r)
        # Dispose fully depreciated assets 1-6 months after the end of their life.
        rng = rng_for(ctx.seed, "disposal", eid, month_start.isoformat())
        for a in self.by_entity[eid]:
            if a.disposed or a.months_done < a.life or rng.random() > 0.25:
                continue
            d = m_end - timedelta(days=rng.randint(1, 20))
            proceeds = round_money(a.cost * Decimal(repr(rng.uniform(0, 0.08))), fc)
            cc = a.row["cost_center_id"] or ctx.org.cc(eid, "D17")
            gain = proceeds - (a.cost - a.accumulated)
            counter = [Line("1590", a.accumulated, fc, None, cc, description="Remove accumulated depreciation"),
                       Line("1500", -a.cost, fc, None, cc, description="Remove asset cost")]
            if gain:
                counter.append(Line("8350", -gain, fc, None, cc, description="Gain on disposal"))
            if proceeds > 0:
                ctx.treasury.pay(eid, d, "INBOUND", "ASSET_SALE", fc, proceeds, counter,
                                 counterparty_type="BUYER", counterparty_name="Asset buyer", cost_center_id=cc,
                                 journal_type="ASSET_DISPOSAL", description=f"Disposal {a.row['asset_number']}")
            else:
                ctx.ledger.post(eid, d, "ASSET_DISPOSAL", counter, source_document_type="FIXED_ASSET",
                                source_document_id=str(a.row["asset_id"]), reference_number=a.row["asset_number"],
                                description="Scrapping of fully depreciated asset")
            a.disposed = True
            a.row = dict(a.row, asset_status="DISPOSED", disposal_date=d, disposal_proceeds=proceeds,
                         updated_at=at(d, 16))
            ctx.sink.emit("erp.fixed_assets", a.row)
