"""Order-to-Cash: opportunity -> sales order -> delivery (COGS) -> invoice -> AR -> receipt/credit note.

Accounting (functional currency, debit-positive):
* Invoice:      Dr 1100 AR (gross)            Cr 4000/4100 revenue (net)   Cr 2200 VAT payable
* Delivery:     Dr 5000 COGS                  Cr 1200 inventory           (product lines only)
* Receipt:      Dr 1010 cash (spot)           Cr 1100 AR (historical)     +/- 8200 realized FX
* Credit note:  Dr 4000/4100 revenue, Dr 2200 Cr 1100 AR                  (at original invoice rate)
* Refund:       Dr 1100 AR                    Cr 1010 cash
* Write-off:    Dr 6420 bad debt              Cr 1100 AR
"""

from __future__ import annotations

import bisect
import heapq
import itertools
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import Line, at, business_day, month_end, rng_for
from finance_common.money import ZERO, round_money

SEASONALITY = [0.82, 0.88, 1.08, 0.95, 0.98, 1.06, 0.86, 0.80, 1.05, 1.04, 1.12, 1.36]
PRODUCTIVITY_GROWTH = 0.035  # annual revenue-per-head improvement on top of headcount growth
_seq = itertools.count()


@dataclass
class OpenInvoice:
    invoice: dict[str, Any]
    customer: Any
    remaining: Decimal
    remaining_functional: Decimal
    revenue_split: list[tuple[str, str, Decimal, Decimal, str | None]]  # group, variant, net, tax, pc
    tax_rate: Decimal
    credited: bool = False
    events: list[tuple] = field(default_factory=list)


class OrderToCash:
    def __init__(self, ctx: Any, customers: list[Any]) -> None:
        self.ctx = ctx
        self.customers_by_entity: dict[str, list[Any]] = {}
        for c in customers:
            self.customers_by_entity.setdefault(c.home_entity_id, []).append(c)
        self.cum_weights = {
            e: list(itertools.accumulate(c.weight for c in cs)) for e, cs in self.customers_by_entity.items()
        }
        self.products_by_line: dict[str, list[dict]] = {}
        for p in ctx.org.products:
            self.products_by_line.setdefault(p["product_line"], []).append(p)
        self.open: dict[int, OpenInvoice] = {}
        self.events: list[tuple] = []  # heap of (date, seq, kind, invoice_id, payload)
        self.price_scale = Decimal("1")
        self.opportunity_seq = 0

    # --------------------------------------------------------------------------- calibration
    def calibrate(self, target_annual_revenue_eur: Decimal, invoices_per_month: int) -> None:
        """Scale list prices so expected annual revenue matches the profile's target.

        The expected customer size factor is weighted by the same weights used to pick customers,
        so enterprise customers' higher purchase frequency is reflected in the calibration.
        """
        rng = rng_for(self.ctx.seed, "calibration")
        all_customers = [c for cs in self.customers_by_entity.values() for c in cs]
        wsum = sum(c.weight for c in all_customers)
        size = Decimal(repr(sum(c.weight * c.size_factor for c in all_customers) / wsum))
        sample = []
        for _ in range(5000):
            total = Decimal(0)
            for _ in range(rng.choice([1, 1, 2, 2, 3])):
                p = rng.choice(self.ctx.org.products)
                total += p["list_price_eur"] * Decimal(rng.randint(1, 8))
            sample.append(total)
        raw_avg = sum(sample) / len(sample) * size
        target_avg = target_annual_revenue_eur / 12 / Decimal(invoices_per_month)
        self.price_scale = (target_avg / raw_avg).quantize(Decimal("0.0001"))

    # ---------------------------------------------------------------------------- generation
    def generate_month(self, entity: Any, month_start: date, invoices_per_month: int, total_weight: float) -> None:
        ctx = self.ctx
        if entity.entity_id not in self.customers_by_entity:
            return
        rng = rng_for(ctx.seed, "o2c", entity.entity_id, month_start.isoformat())
        expected = invoices_per_month * entity.sales_weight / total_weight * SEASONALITY[month_start.month - 1] \
            * ctx.sales_growth_index(month_start)
        n = max(0, round(rng.gauss(expected, max(1.0, expected ** 0.5))))
        last_day = month_end(month_start)
        for _ in range(n):
            inv_date = month_start + timedelta(days=rng.randint(0, (last_day - month_start).days))
            if inv_date.weekday() >= 5:
                inv_date = business_day(inv_date, forward=False) if inv_date.day > 3 else business_day(inv_date)
            if inv_date > ctx.end or inv_date < month_start:
                continue
            self._invoice(entity, inv_date, rng)

    def _pick_customer(self, entity_id: str, rng) -> Any:
        cum = self.cum_weights[entity_id]
        idx = bisect.bisect_left(cum, rng.random() * cum[-1])
        return self.customers_by_entity[entity_id][min(idx, len(cum) - 1)]

    def _invoice(self, entity: Any, inv_date: date, rng) -> None:
        ctx = self.ctx
        eid, fc = entity.entity_id, entity.functional_currency
        cust = self._pick_customer(eid, rng)
        ccy = cust.billing_currency
        pcs = ctx.org.entity_profit_centers.get(eid, {})
        lines_available = [ln for ln in pcs if ln in self.products_by_line]
        fx_to_ccy = ctx.fx.spot(inv_date, "EUR", ccy)
        tax_rate = ctx.vat_rates[entity.country] if cust.country == entity.country else ZERO
        variant = "domestic" if cust.country == entity.country else "export"
        sales_cc = ctx.org.cc(eid, "D06" if cust.segment in ("Enterprise", "Public Sector") else "D07", "D06")

        # --- opportunity + sales order (CRM)
        order_date = inv_date - timedelta(days=rng.randint(0, 12))
        delivery_date = inv_date
        line_rows, revenue_split, cogs = [], [], []
        subtotal = ZERO
        for ln_no in range(1, rng.choice([1, 1, 2, 2, 3]) + 1):
            line = rng.choice(lines_available)
            prod = rng.choice(self.products_by_line[line])
            qty = Decimal(rng.randint(1, 8))
            price = round_money(prod["list_price_eur"] * self.price_scale * Decimal(repr(cust.size_factor))
                                * Decimal(repr(rng.uniform(0.9, 1.1))) * fx_to_ccy, ccy)
            net = round_money(qty * price, ccy)
            tax = round_money(net * tax_rate / 100, ccy)
            subtotal += net
            group = "4000" if prod["revenue_type"] == "PRODUCT" else "4100"
            pc = pcs[line]
            line_rows.append((ln_no, prod, qty, price, net, tax, pc, group))
            revenue_split.append((group, variant, net, tax, pc))
            if prod["standard_cost_ratio"] > 0:
                cogs.append((net, prod["standard_cost_ratio"], pc))
        tax_total = sum((r[5] for r in line_rows), ZERO)
        total = subtotal + tax_total

        self.opportunity_seq += 1
        opp_id = self.opportunity_seq
        opp_created = order_date - timedelta(days=rng.randint(20, 120))
        so_id = ctx.ids.next("sales_order")
        ctx.crm_opportunity(opp_id, cust, eid, f"{cust.name.split(' ')[0]} {line_rows[0][1]['product_line']} deal",
                            subtotal, ccy, opp_created, order_date, won=True)
        ctx.sink.emit("crm.sales_orders", {
            "sales_order_id": so_id, "order_number": f"SO{so_id:08d}", "customer_id": cust.customer_id,
            "opportunity_id": opp_id, "entity_id": eid, "order_date": order_date, "delivery_date": None,
            "currency": ccy, "order_amount": subtotal, "order_status": "CONFIRMED",
            "created_at": at(order_date, 10), "updated_at": at(order_date, 10),
        })
        ctx.sink.emit("crm.sales_orders", {
            "sales_order_id": so_id, "order_number": f"SO{so_id:08d}", "customer_id": cust.customer_id,
            "opportunity_id": opp_id, "entity_id": eid, "order_date": order_date, "delivery_date": delivery_date,
            "currency": ccy, "order_amount": subtotal, "order_status": "DELIVERED",
            "created_at": at(order_date, 10), "updated_at": at(delivery_date, 12),
        })
        # Lost / open opportunities around each won deal (pipeline realism).
        for _ in range(rng.choice([0, 1, 1, 2])):
            self.opportunity_seq += 1
            lost_created = opp_created + timedelta(days=rng.randint(-30, 30))
            close = lost_created + timedelta(days=rng.randint(30, 150))
            ctx.crm_opportunity(self.opportunity_seq, cust, eid, f"{cust.name.split(' ')[0]} expansion",
                                round_money(subtotal * Decimal(repr(rng.uniform(0.5, 2.0))), ccy), ccy,
                                lost_created, close, won=False)

        # --- COGS at delivery (product lines)
        rate = ctx.fx.spot(inv_date, ccy, fc)
        if cogs:
            cogs_lines = []
            for net, ratio, pc in cogs:
                amt = round_money(net * rate * ratio, fc)
                cogs_lines += [Line("5000", amt, fc, None, sales_cc, pc, description="Cost of goods delivered"),
                               Line("1200", -amt, fc, None, sales_cc, pc, description="Inventory issue")]
            ctx.ledger.post(eid, delivery_date, "COGS", cogs_lines, source_document_type="SALES_ORDER",
                            source_document_id=str(so_id), reference_number=f"SO{so_id:08d}",
                            description="Goods delivery", source_system="ERP")
            ctx.inventory_consumed[eid] += sum((ln.amount for ln in cogs_lines if ln.amount > 0), ZERO)

        # --- invoice + AR journal
        invoice_id = ctx.ids.next("invoice")
        number = f"INV-{eid}-{inv_date:%Y}-{invoice_id:08d}"
        jl = [Line("1100", total, ccy, None, sales_cc, description=f"Invoice {number}")]
        for group, var, net, tax, pc in revenue_split:
            jl.append(Line(group, -net, ccy, None, sales_cc, pc, account_variant=var, description="Revenue"))
        if tax_total:
            jl.append(Line("2200", -tax_total, ccy, None, sales_cc, description="Output VAT"))
        created = at(inv_date, 14, rng.randint(0, 59))
        journal_id = ctx.ledger.post(eid, inv_date, "AR_INVOICE", jl, source_document_type="CUSTOMER_INVOICE",
                                     source_document_id=str(invoice_id), reference_number=number,
                                     description=f"Customer invoice {cust.name}", created_at=created)
        functional_total = round_money(total * rate, fc)
        due = inv_date + timedelta(days=cust.payment_terms_days)
        inv = {
            "invoice_id": invoice_id, "invoice_number": number, "erp_customer_id": cust.erp_customer_id,
            "entity_id": eid, "sales_order_id": so_id, "invoice_date": inv_date, "due_date": due, "currency": ccy,
            "subtotal": subtotal, "tax_amount": tax_total, "invoice_amount": total, "outstanding_amount": total,
            "invoice_status": "OPEN", "is_intercompany": False, "counterparty_entity_id": None,
            "journal_id": journal_id, "is_deleted": False, "created_at": created, "updated_at": created,
        }
        ctx.sink.emit("erp.customer_invoices", inv)
        for ln_no, prod, qty, price, net, tax, pc, group in line_rows:
            ctx.sink.emit("erp.customer_invoice_lines", {
                "invoice_line_id": ctx.ids.next("invoice_line"), "invoice_id": invoice_id, "line_number": ln_no,
                "product_id": prod["product_id"], "quantity": qty, "unit_price": price, "line_amount": net,
                "tax_rate_pct": tax_rate, "tax_amount": tax, "profit_center_id": pc,
                "revenue_account_id": ctx.coa.account_for(eid, group, variant),
                "created_at": created, "updated_at": created,
            })
        if tax_total:
            ctx.tax_txn(eid, inv_date, "OUTPUT", "CUSTOMER_INVOICE", invoice_id, subtotal, tax_rate, tax_total, ccy,
                        round_money(tax_total * rate, fc))
        oi = OpenInvoice(inv, cust, total, functional_total, revenue_split, tax_rate)
        self.open[invoice_id] = oi
        self._schedule(oi, rng)

    # ----------------------------------------------------------------------- settlement planning
    def _schedule(self, oi: OpenInvoice, rng) -> None:
        inv, cust = oi.invoice, oi.customer
        inv_date, due = inv["invoice_date"], inv["due_date"]
        if rng.random() < 0.03:  # credit note
            cn_date = inv_date + timedelta(days=rng.randint(5, 45))
            frac = Decimal("1") if rng.random() < 0.3 else Decimal(repr(round(rng.uniform(0.05, 0.4), 2)))
            self._push(cn_date, "CREDIT_NOTE", inv["invoice_id"], frac)
        b = cust.behavior
        never = b == "DELINQUENT" and rng.random() < 0.45
        if never:
            self._push(inv_date + timedelta(days=400), "WRITE_OFF", inv["invoice_id"], None)
            return
        offset = {"PROMPT": rng.randint(-10, 0), "NORMAL": rng.randint(-3, 15), "LATE": rng.randint(20, 95),
                  "DELINQUENT": rng.randint(60, 220)}[b]
        pay = max(inv_date + timedelta(days=1), due + timedelta(days=offset))
        if cust.batch_payer:
            pay = date(pay.year, pay.month, min(25, 28)) if pay.day <= 25 else (
                date(pay.year + (pay.month == 12), pay.month % 12 + 1, 25))
            pay = max(pay, inv_date + timedelta(days=1))
        pay = business_day(pay)
        if rng.random() < 0.08:  # partial settlement in two installments
            self._push(pay, "RECEIPT", inv["invoice_id"], Decimal("0.6"))
            self._push(business_day(pay + timedelta(days=rng.randint(20, 45))), "RECEIPT", inv["invoice_id"], None)
        else:
            self._push(pay, "RECEIPT", inv["invoice_id"], None)

    def _push(self, d: date, kind: str, invoice_id: int, payload: Any) -> None:
        heapq.heappush(self.events, (d, next(_seq), kind, invoice_id, payload))

    # -------------------------------------------------------------------------- event processing
    def process_until(self, until: date) -> None:
        """Process all AR events dated <= until (credit notes, receipts, write-offs, refunds)."""
        receipts: dict[tuple[int, date, str], list[tuple[int, Decimal | None]]] = {}
        while self.events and self.events[0][0] <= until:
            d, _, kind, inv_id, payload = heapq.heappop(self.events)
            if d > self.ctx.end:
                continue
            oi = self.open.get(inv_id)
            if oi is None:
                continue
            if kind == "RECEIPT":
                key = (oi.customer.erp_customer_id, d, oi.invoice["currency"])
                receipts.setdefault(key, []).append((inv_id, payload))
            else:
                self._flush_receipts(receipts, before=d)
                if kind == "CREDIT_NOTE":
                    self._credit_note(oi, d, payload)
                elif kind == "WRITE_OFF":
                    self._write_off(oi, d)
                elif kind == "REFUND":
                    self._refund(oi, d, payload)
        self._flush_receipts(receipts, before=None)

    def _flush_receipts(self, receipts: dict, before: date | None) -> None:
        for key in sorted(k for k in receipts if before is None or k[1] <= before):
            self._receipt(key, receipts.pop(key))

    def _receipt(self, key: tuple[int, date, str], items: list[tuple[int, Decimal | None]]) -> None:
        ctx = self.ctx
        _, pay_date, ccy = key
        allocations = []
        for inv_id, frac in items:
            oi = self.open[inv_id]
            if oi.remaining <= 0:
                continue
            amt = oi.remaining if frac is None else round_money(oi.invoice["invoice_amount"] * frac, ccy)
            amt = min(amt, oi.remaining)
            allocations.append((oi, amt))
        if not allocations:
            return
        oi0 = allocations[0][0]
        eid = oi0.invoice["entity_id"]
        fc = ctx.entities[eid].functional_currency
        total = sum((a for _, a in allocations), ZERO)
        rng = rng_for(ctx.seed, "receipt", oi0.invoice["invoice_id"], pay_date.isoformat())
        charge = ZERO
        if ccy != fc and rng.random() < 0.15:
            charge = round_money(Decimal(15) * ctx.fx.spot(pay_date, "EUR", ccy), ccy)
        purpose = "COLLECTIONS" if ccy == fc else None
        ba = ctx.treasury.account(eid, ccy, purpose)
        counter, reliefs = [], []
        cc = ctx.org.cc(eid, "D17")
        for oi, amt in allocations:
            relief = oi.remaining_functional if amt == oi.remaining else round_money(
                oi.remaining_functional * amt / oi.remaining, fc)
            counter.append(Line("1100", -amt, ccy, -relief, cc, description=f"Settle {oi.invoice['invoice_number']}"))
            reliefs.append(relief)
        payment = ctx.treasury.pay(
            eid, pay_date, "INBOUND", "CUSTOMER_RECEIPT", ccy, total, counter, ba_id=ba,
            counterparty_type="CUSTOMER", counterparty_id=str(oi0.customer.erp_customer_id),
            counterparty_name=oi0.customer.name, bank_charge=charge, cost_center_id=cc,
            missing_bank_reference=rng.random() < 0.04, journal_type="AR_RECEIPT",
        )
        for (oi, amt), relief in zip(allocations, reliefs, strict=True):
            ctx.sink.emit("erp.payment_allocations", {
                "allocation_id": ctx.ids.next("allocation"), "payment_id": payment["payment_id"],
                "document_type": "CUSTOMER_INVOICE", "document_id": oi.invoice["invoice_id"],
                "allocation_date": pay_date, "currency": ccy, "allocated_amount": amt, "discount_amount": ZERO,
                "functional_amount_relieved": relief, "created_at": payment["created_at"],
                "updated_at": payment["created_at"],
            })
            oi.remaining -= amt
            oi.remaining_functional -= relief
            self._version(oi, pay_date, "PAID" if oi.remaining == 0 else "PARTIALLY_PAID")

    def _version(self, oi: OpenInvoice, d: date, status: str) -> None:
        oi.invoice = dict(oi.invoice, outstanding_amount=oi.remaining, invoice_status=status,
                          updated_at=at(d, 18, int(oi.invoice["invoice_id"]) % 60))
        self.ctx.sink.emit("erp.customer_invoices", oi.invoice)

    def _credit_note(self, oi: OpenInvoice, d: date, frac: Decimal) -> None:
        ctx = self.ctx
        inv = oi.invoice
        eid, ccy = inv["entity_id"], inv["currency"]
        fc = ctx.entities[eid].functional_currency
        if oi.credited:
            return
        oi.credited = True
        subtotal = round_money(inv["subtotal"] * frac, ccy)
        tax = round_money(subtotal * oi.tax_rate / 100, ccy)
        total = subtotal + tax
        inv_rate = ctx.fx.spot(inv["invoice_date"], ccy, fc)
        functional = round_money(total * inv_rate, fc)
        cc = ctx.org.cc(eid, "D07", "D06")
        cn_id = ctx.ids.next("credit_note")
        number = f"CN-{eid}-{d:%Y}-{cn_id:07d}"
        lines = [Line("1100", -total, ccy, -functional, cc, description=f"Credit note {number}")]
        # Reverse revenue pro rata over the original revenue split at the historical invoice rate.
        net_total = sum((s[2] for s in oi.revenue_split), ZERO)
        rev_f_total = functional - round_money(tax * inv_rate, fc)
        acc_f = ZERO
        for i, (group, var, net, _tax, pc) in enumerate(oi.revenue_split):
            part = rev_f_total - acc_f if i == len(oi.revenue_split) - 1 else round_money(rev_f_total * net / net_total, fc)
            acc_f += part
            lines.append(Line(group, round_money(subtotal * net / net_total, ccy), ccy, part, cc, pc,
                              account_variant=var, description="Revenue reversal"))
        if tax:
            lines.append(Line("2200", tax, ccy, round_money(tax * inv_rate, fc), cc, description="Output VAT reversal"))
        created = at(d, 11)
        posting = ctx.periods.resolve_posting_date(eid, d, created)
        journal_id = ctx.ledger.post(eid, posting, "AR_CREDIT_NOTE", lines, source_document_type="CREDIT_NOTE",
                                     source_document_id=str(cn_id), reference_number=number,
                                     description="Customer credit note", created_at=created)
        ctx.sink.emit("erp.credit_notes", {
            "credit_note_id": cn_id, "credit_note_number": number, "invoice_id": inv["invoice_id"],
            "erp_customer_id": inv["erp_customer_id"], "entity_id": eid, "credit_note_date": posting,
            "currency": ccy, "subtotal": subtotal, "tax_amount": tax, "credit_amount": total,
            "functional_amount": functional, "reason_code": "FULL_CREDIT" if frac == 1 else "PRICE_ADJUSTMENT",
            "journal_id": journal_id, "created_at": created, "updated_at": created,
        })
        if tax:
            ctx.tax_txn(eid, posting, "OUTPUT", "CREDIT_NOTE", cn_id, -subtotal, oi.tax_rate, -tax, ccy,
                        -round_money(tax * inv_rate, fc))
        oi.remaining -= total
        oi.remaining_functional -= functional
        if oi.remaining < 0:
            # Invoice already settled: customer has a credit balance -> refund 7-20 days later.
            self._push(business_day(posting + timedelta(days=10)), "REFUND", inv["invoice_id"], cn_id)
            self._version(oi, posting, "CREDITED")
        else:
            self._version(oi, posting, "CREDITED" if oi.remaining == 0 else inv["invoice_status"])

    def _refund(self, oi: OpenInvoice, d: date, cn_id: int) -> None:
        ctx = self.ctx
        inv = oi.invoice
        eid, ccy = inv["entity_id"], inv["currency"]
        amt = -oi.remaining
        cc = ctx.org.cc(eid, "D17")
        ctx.treasury.ensure_funds(eid, d, ccy, amt)
        payment = ctx.treasury.pay(
            eid, d, "OUTBOUND", "CUSTOMER_REFUND", ccy, amt,
            [Line("1100", amt, ccy, -oi.remaining_functional, cc, description="Customer refund")],
            counterparty_type="CUSTOMER", counterparty_id=str(inv["erp_customer_id"]),
            counterparty_name=oi.customer.name, cost_center_id=cc, journal_type="AR_REFUND",
        )
        ctx.sink.emit("erp.payment_allocations", {
            "allocation_id": ctx.ids.next("allocation"), "payment_id": payment["payment_id"],
            "document_type": "CREDIT_NOTE", "document_id": cn_id, "allocation_date": d, "currency": ccy,
            "allocated_amount": -amt, "discount_amount": ZERO,
            "functional_amount_relieved": oi.remaining_functional,
            "created_at": payment["created_at"], "updated_at": payment["created_at"],
        })
        oi.remaining = ZERO
        oi.remaining_functional = ZERO
        self._version(oi, d, "CREDITED")

    def _write_off(self, oi: OpenInvoice, d: date) -> None:
        ctx = self.ctx
        inv = oi.invoice
        if oi.remaining <= 0:
            return
        eid, ccy = inv["entity_id"], inv["currency"]
        cc = ctx.org.cc(eid, "D17")
        cn_id = ctx.ids.next("credit_note")
        number = f"WO-{eid}-{d:%Y}-{cn_id:07d}"
        created = at(d, 16)
        posting = ctx.periods.resolve_posting_date(eid, d, created)
        lines = [Line("6420", oi.remaining, ccy, oi.remaining_functional, cc, description="Bad debt write-off"),
                 Line("1100", -oi.remaining, ccy, -oi.remaining_functional, cc, description=f"Write-off {number}")]
        jid = ctx.ledger.post(eid, posting, "AR_WRITE_OFF", lines, source_document_type="CREDIT_NOTE",
                              source_document_id=str(cn_id), reference_number=number,
                              description="Bad debt write-off", created_at=created)
        ctx.sink.emit("erp.credit_notes", {
            "credit_note_id": cn_id, "credit_note_number": number, "invoice_id": inv["invoice_id"],
            "erp_customer_id": inv["erp_customer_id"], "entity_id": eid, "credit_note_date": posting,
            "currency": ccy, "subtotal": oi.remaining, "tax_amount": ZERO, "credit_amount": oi.remaining,
            "functional_amount": oi.remaining_functional, "reason_code": "BAD_DEBT_WRITE_OFF", "journal_id": jid,
            "created_at": created, "updated_at": created,
        })
        oi.remaining = ZERO
        oi.remaining_functional = ZERO
        self._version(oi, posting, "WRITTEN_OFF")
