"""Procure-to-Pay: requisition -> PO -> goods receipt -> supplier invoice -> AP -> payment run.

Accounting (functional currency, debit-positive):
* Supplier invoice:  Dr expense / 1200 inventory / 1500 PP&E / 1300 prepaid, Dr 1400 VAT  Cr 2000 AP
* Payment:           Dr 2000 AP (historical)   Cr 1010 cash (spot)  Cr 8300 discount  +/- 8200 FX
* Utility accrual:   Dr 6350 Cr 2100 at month end, reversed on day 1 of the next month
* Prepaid licence:   Dr 1300 at invoice, monthly Dr 6100 Cr 1300 amortization

Injected exceptions for three-way matching: price variance, short receipt, missing receipt,
invoice without PO ("unauthorized") and duplicate supplier invoices (most blocked, some paid).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import Line, add_months, at, business_day, month_end, rng_for
from data_generator.vendors import CATEGORY_ACCOUNT
from finance_common.money import ZERO, round_money

OPEX_SHARE = {  # share of the entity monthly cost driver (EUR)
    "SOFTWARE": Decimal("0.030"),
    "MARKETING": Decimal("0.050"),
    "OFFICE": Decimal("0.012"),
    "TRAVEL": Decimal("0.008"),
    "PROFESSIONAL": Decimal("0.018"),
    "IT_HARDWARE": Decimal("0.010"),
}
RENT_SHARE = Decimal("0.022")
UTILITIES_SHARE = Decimal("0.006")
PREPAID_LICENCE_SHARE = Decimal("0.06")  # annual licence = 6% of one month's driver x 12 / 12
CAPEX_SHARE = Decimal("0.018")


@dataclass
class OpenPayable:
    invoice: dict[str, Any]
    vendor: Any
    remaining: Decimal
    remaining_functional: Decimal
    planned_pay_date: date
    take_discount: bool


class ProcureToPay:
    def __init__(self, ctx: Any, vendors_by_entity_cat: dict[tuple[str, str], list[Any]]) -> None:
        self.ctx = ctx
        self.vendors = vendors_by_entity_cat
        self.open: dict[int, OpenPayable] = {}
        self.prepaids: list[tuple[str, date, Decimal, str, int]] = []  # entity, start, monthly, cc, months left
        self.accruals: dict[tuple[str, date], int] = {}
        self.invoice_numbers: set[tuple[int, str]] = set()

    def _vendor(self, eid: str, cat: str, rng) -> Any:
        vs = self.vendors.get((eid, cat)) or self.vendors.get((eid, "OFFICE"))
        return rng.choice(vs)

    # ------------------------------------------------------------------------------ generation
    def generate_month(self, entity: Any, month_start: date, sales_count: int) -> None:
        ctx = self.ctx
        eid, fc = entity.entity_id, entity.functional_currency
        rng = rng_for(ctx.seed, "p2p", eid, month_start.isoformat())
        driver_eur = ctx.cost_driver_eur(eid, month_start)
        to_fc = ctx.fx.spot(month_start, "EUR", fc)
        driver = driver_eur * to_fc
        m_end = month_end(month_start)
        _g_and_a = ctx.org.cc(eid, "D17", "D24")
        facilities = ctx.org.cc(eid, "D22", "D17")

        # Rent (fixed, invoiced on the 1st business day) and utilities (actual for previous month).
        self.vendor_invoice(
            entity,
            "RENT",
            business_day(month_start),
            round_money(driver * RENT_SHARE, fc),
            rng,
            cost_center=facilities,
            description="Office rent",
        )
        if month_start > ctx.start:
            prev = add_months(month_start, -1)
            est = round_money(ctx.cost_driver_eur(eid, prev) * ctx.fx.spot(prev, "EUR", fc) * UTILITIES_SHARE, fc)
            actual = round_money(est * Decimal(repr(rng.uniform(0.92, 1.1))), fc)
            self.vendor_invoice(
                entity,
                "UTILITIES",
                month_start + timedelta(days=rng.randint(4, 12)),
                actual,
                rng,
                cost_center=facilities,
                description=f"Utilities {prev:%Y-%m}",
            )
        # Prepaid annual software licence every January.
        if month_start.month == 1:
            amount = round_money(driver * PREPAID_LICENCE_SHARE * 12, fc)
            self.vendor_invoice(
                entity,
                "SOFTWARE",
                month_start + timedelta(days=rng.randint(2, 10)),
                amount,
                rng,
                cost_center=ctx.org.cc(eid, "D21", "D17"),
                description="Annual licence (prepaid)",
                account_override="1300",
            )
            self.prepaids.append((eid, month_start, round_money(amount / 12, fc), ctx.org.cc(eid, "D21", "D17"), 12))
        # Operating expenses.
        n_other = max(2, round(sales_count * 0.55))
        for cat, share in OPEX_SHARE.items():
            if cat == "MARKETING" and entity.entity_type != "OPERATING":
                share = share / 10
            n = max(1, round(n_other * float(share / sum(OPEX_SHARE.values()))))
            for _ in range(n):
                amount = round_money(driver * share / n * Decimal(repr(rng.uniform(0.6, 1.4))), fc)
                d = month_start + timedelta(days=rng.randint(0, (m_end - month_start).days))
                cc = rng.choice(ctx.org.entity_cost_centers[eid])
                if cat == "IT_HARDWARE":
                    self.purchase_order_flow(entity, cat, d, amount, rng, cc)
                else:
                    self.vendor_invoice(entity, cat, d, amount, rng, cost_center=cc)
        # Inventory replenishment to cover last month's consumption.
        if entity.entity_type == "OPERATING":
            consumed = ctx.inventory_consumed_last.get(eid, ZERO)
            if consumed > 0:
                n_po = max(1, round(sales_count * 0.12))
                for _ in range(n_po):
                    amount = round_money(consumed / n_po * Decimal(repr(rng.uniform(0.85, 1.2))), fc)
                    d = month_start + timedelta(days=rng.randint(0, 20))
                    self.purchase_order_flow(entity, "INVENTORY", d, amount, rng, ctx.org.cc(eid, "D02", "D07", "D06"))
        # Capital expenditure (lumpy).
        if rng.random() < 0.35:
            amount = round_money(driver * CAPEX_SHARE * Decimal(repr(rng.uniform(1.5, 4.0))), fc)
            d = month_start + timedelta(days=rng.randint(0, 25))
            self.purchase_order_flow(entity, "CAPEX", d, amount, rng, rng.choice(ctx.org.entity_cost_centers[eid]))

    def month_end(self, entity: Any, month_start: date) -> None:
        """Accrue utilities for the month (reversed on day 1 of next month) and amortize prepaids."""
        ctx = self.ctx
        eid, fc = entity.entity_id, entity.functional_currency
        m_end = month_end(month_start)
        cc = ctx.org.cc(eid, "D22", "D17")
        est = round_money(
            ctx.cost_driver_eur(eid, month_start) * ctx.fx.spot(month_start, "EUR", fc) * UTILITIES_SHARE, fc
        )
        created = at(m_end, 19)
        lines = [
            Line("6350", est, fc, None, cc, description="Utilities accrual"),
            Line("2100", -est, fc, None, cc, description="Utilities accrual"),
        ]
        jid = ctx.ledger.post(
            eid,
            m_end,
            "ACCRUAL",
            lines,
            source_document_type="ACCRUAL",
            source_document_id=f"ACR-UTIL-{eid}-{m_end:%Y%m}",
            reference_number=f"ACR-UTIL-{eid}-{m_end:%Y%m}",
            description="Month-end utilities accrual",
            created_at=created,
            created_by="close.automation",
        )
        nxt = m_end + timedelta(days=1)
        if nxt <= ctx.end:
            rev = [
                Line("6350", -est, fc, None, cc, description="Reverse utilities accrual"),
                Line("2100", est, fc, None, cc, description="Reverse utilities accrual"),
            ]
            ctx.ledger.post(
                eid,
                nxt,
                "REVERSAL",
                rev,
                source_document_type="ACCRUAL",
                source_document_id=f"ACR-UTIL-{eid}-{m_end:%Y%m}",
                reference_number=f"REV-ACR-UTIL-{eid}-{m_end:%Y%m}",
                description="Auto-reversal of accrual",
                created_at=at(nxt, 6),
                reversal_of=jid,
                created_by="close.automation",
            )
        keep = []
        for e, start, monthly, pcc, left in self.prepaids:
            if e == eid and start <= month_start and left > 0:
                ctx.ledger.post(
                    eid,
                    m_end,
                    "PREPAID_AMORTIZATION",
                    [
                        Line("6100", monthly, fc, None, pcc, description="Licence amortization"),
                        Line("1300", -monthly, fc, None, pcc, description="Licence amortization"),
                    ],
                    source_document_type="PREPAID",
                    source_document_id=f"PPD-{eid}-{start:%Y}",
                    reference_number=f"PPD-{eid}-{start:%Y}-{m_end:%m}",
                    created_at=at(m_end, 19, 30),
                    description="Prepaid licence amortization",
                    created_by="close.automation",
                )
                left -= 1
            keep.append((e, start, monthly, pcc, left))
        self.prepaids = [p for p in keep if p[4] > 0]

    # ---------------------------------------------------------------------------------- PO flow
    def purchase_order_flow(self, entity: Any, cat: str, d: date, amount_fc: Decimal, rng, cc: str) -> None:
        ctx = self.ctx
        eid, fc = entity.entity_id, entity.functional_currency
        vendor = self._vendor(eid, cat, rng)
        ccy = vendor.currency
        amount = round_money(amount_fc * ctx.fx.spot(d, fc, ccy), ccy)
        if amount <= 0:
            return
        req_id = ctx.ids.next("requisition")
        req_date = d - timedelta(days=rng.randint(2, 10))
        ctx.sink.emit(
            "erp.purchase_requisitions",
            {
                "requisition_id": req_id,
                "entity_id": eid,
                "requested_by_employee_id": ctx.employee_in_cc(cc, rng),
                "cost_center_id": cc,
                "requisition_date": req_date,
                "estimated_amount": amount,
                "currency": ccy,
                "approval_status": "APPROVED",
                "created_at": at(req_date, 9),
                "updated_at": at(req_date, 15),
            },
        )
        po_id = ctx.ids.next("po")
        n_lines = rng.choice([1, 2, 3])
        po_lines = []
        for ln in range(1, n_lines + 1):
            qty = Decimal(rng.randint(5, 120))
            unit = round_money(amount / n_lines / qty, ccy)
            if unit <= 0:
                unit = Decimal(1)
            po_lines.append(
                {
                    "po_line_id": ctx.ids.next("po_line"),
                    "purchase_order_id": po_id,
                    "line_number": ln,
                    "product_id": None,
                    "description": f"{cat.title()} item {ln}",
                    "quantity": qty,
                    "unit_price": unit,
                    "line_amount": round_money(qty * unit, ccy),
                    "cost_center_id": cc,
                    "created_at": at(d, 10),
                    "updated_at": at(d, 10),
                }
            )
        order_amount = sum((p["line_amount"] for p in po_lines), ZERO)
        po = {
            "purchase_order_id": po_id,
            "po_number": f"PO-{eid}-{po_id:08d}",
            "requisition_id": req_id,
            "vendor_id": vendor.vendor_id,
            "entity_id": eid,
            "order_date": d,
            "currency": ccy,
            "order_amount": order_amount,
            "po_status": "OPEN",
            "created_at": at(d, 10),
            "updated_at": at(d, 10),
        }
        ctx.sink.emit("erp.purchase_orders", po)
        for p in po_lines:
            ctx.sink.emit("erp.purchase_order_lines", p)
        scenario = rng.random()
        receipt_date = d + timedelta(days=rng.randint(4, 20))
        missing_gr = scenario < 0.01
        short = 0.01 <= scenario < 0.04
        price_var = 0.04 <= scenario < 0.06
        if not missing_gr and receipt_date <= ctx.end:
            for p in po_lines:
                qty = p["quantity"] - (Decimal(max(1, int(p["quantity"] * Decimal("0.1")))) if short else 0)
                ctx.sink.emit(
                    "erp.goods_receipts",
                    {
                        "goods_receipt_id": ctx.ids.next("gr"),
                        "po_line_id": p["po_line_id"],
                        "purchase_order_id": po_id,
                        "receipt_date": receipt_date,
                        "quantity_received": qty,
                        "created_at": at(receipt_date, 13),
                        "updated_at": at(receipt_date, 13),
                    },
                )
        inv_date = receipt_date + timedelta(days=rng.randint(0, 8))
        if inv_date > ctx.end:
            return
        inv_lines = []
        for p in po_lines:
            unit = p["unit_price"]
            if price_var:
                unit = round_money(unit * Decimal(repr(rng.uniform(1.03, 1.08))), ccy)
            inv_lines.append((p["po_line_id"], p["description"], p["quantity"], unit, p["cost_center_id"]))
        self.vendor_invoice(entity, cat, inv_date, None, rng, vendor=vendor, po=po, lines=inv_lines, cost_center=cc)
        ctx.sink.emit("erp.purchase_orders", dict(po, po_status="INVOICED", updated_at=at(inv_date, 16)))

    # ---------------------------------------------------------------------------- supplier invoice
    def vendor_invoice(
        self,
        entity: Any,
        cat: str,
        d: date,
        amount_fc: Decimal | None,
        rng,
        *,
        vendor=None,
        po=None,
        lines=None,
        cost_center: str | None = None,
        description: str | None = None,
        account_override: str | None = None,
        duplicate_of: dict | None = None,
    ) -> dict | None:
        ctx = self.ctx
        eid, fc = entity.entity_id, entity.functional_currency
        vendor = vendor or self._vendor(eid, cat, rng)
        ccy = vendor.currency
        if d > ctx.end:
            return None
        if lines is None:
            amount = round_money(amount_fc * ctx.fx.spot(d, fc, ccy), ccy)
            lines = [(None, description or f"{cat.title()} services", Decimal(1), amount, cost_center)]
        domestic = vendor.country == entity.country
        tax_rate = ctx.vat_rates[entity.country] if domestic and not vendor.is_intercompany else ZERO
        account = account_override or CATEGORY_ACCOUNT.get(cat, "6650")
        received = d + timedelta(days=rng.choice([0, 1, 2, 3, 5, 9, 14]))
        if duplicate_of is not None:  # the same invoice re-submitted by the supplier later
            received = duplicate_of["received_date"] + timedelta(days=rng.randint(5, 20))
        if received > ctx.end:
            return None
        created = at(received, 10, rng.randint(0, 59))
        vi_id = ctx.ids.next("vendor_invoice")
        number = duplicate_of["vendor_invoice_number"] if duplicate_of else f"{vendor.vendor_id % 997:03d}-{vi_id:08d}"
        unauthorized = po is None and cat == "INVENTORY"
        line_rows, subtotal, tax_total = [], ZERO, ZERO
        for n, (po_line_id, desc, qty, unit, cc) in enumerate(lines, start=1):
            net = round_money(qty * unit, ccy)
            tax = round_money(net * tax_rate / 100, ccy)
            subtotal += net
            tax_total += tax
            line_rows.append((n, po_line_id, desc, qty, unit, net, tax, cc or cost_center))
        total = subtotal + tax_total
        blocked = duplicate_of is not None and rng.random() < 0.7
        posting = ctx.periods.resolve_posting_date(eid, d, created)
        due = d + timedelta(days=vendor.terms)
        journal_id = None
        ap_functional = round_money(-total * ctx.fx.spot(posting, ccy, fc), fc)
        if not blocked:
            ap = "2050" if vendor.is_intercompany else "2000"
            jl = [
                Line(
                    ap,
                    -total,
                    ccy,
                    ap_functional,
                    cost_center,
                    counterparty_entity_id=vendor.ic_entity_id,
                    description=f"Supplier invoice {number}",
                )
            ]
            for _n, _po_line_id, desc, _qty, _unit, net, _tax, cc in line_rows:
                jl.append(
                    Line(account, net, ccy, None, cc, counterparty_entity_id=vendor.ic_entity_id, description=desc)
                )
            if tax_total:
                jl.append(Line("1400", tax_total, ccy, None, cost_center, description="Input VAT"))
            journal_id = ctx.ledger.post(
                eid,
                posting,
                "AP_INVOICE",
                jl,
                source_document_type="VENDOR_INVOICE",
                source_document_id=str(vi_id),
                reference_number=number,
                description=f"Supplier invoice {vendor.name}",
                created_at=created,
                transaction_date=d,
            )
        inv = {
            "vendor_invoice_id": vi_id,
            "vendor_invoice_number": number,
            "vendor_id": vendor.vendor_id,
            "purchase_order_id": po["purchase_order_id"] if po else None,
            "entity_id": eid,
            "invoice_date": d,
            "received_date": received,
            "due_date": due,
            "currency": ccy,
            "subtotal": subtotal,
            "tax_amount": tax_total,
            "invoice_amount": total,
            "approved_amount": ZERO if blocked else total,
            "outstanding_amount": ZERO if blocked else total,
            "payment_status": "BLOCKED" if blocked else "OPEN",
            "approval_status": "REJECTED_DUPLICATE" if blocked else ("PENDING_REVIEW" if unauthorized else "APPROVED"),
            "expense_category": cat,
            "is_intercompany": vendor.is_intercompany,
            "counterparty_entity_id": vendor.ic_entity_id,
            "journal_id": journal_id,
            "created_at": created,
            "updated_at": created,
        }
        ctx.sink.emit("erp.vendor_invoices", inv)
        for n, po_line_id, desc, qty, unit, net, tax, cc in line_rows:
            ctx.sink.emit(
                "erp.vendor_invoice_lines",
                {
                    "vendor_invoice_line_id": ctx.ids.next("vendor_invoice_line"),
                    "vendor_invoice_id": vi_id,
                    "line_number": n,
                    "po_line_id": po_line_id,
                    "description": desc,
                    "quantity": qty,
                    "unit_price": unit,
                    "line_amount": net,
                    "tax_rate_pct": tax_rate,
                    "tax_amount": tax,
                    "expense_account_id": ctx.coa.account_for(eid, account),
                    "cost_center_id": cc,
                    "created_at": created,
                    "updated_at": created,
                },
            )
        if blocked:
            return inv
        rate = ctx.fx.spot(posting, ccy, fc)
        if tax_total:
            ctx.tax_txn(
                eid,
                posting,
                "INPUT",
                "VENDOR_INVOICE",
                vi_id,
                subtotal,
                tax_rate,
                tax_total,
                ccy,
                round_money(tax_total * rate, fc),
            )
        if cat == "CAPEX":
            ctx.assets.register_acquisition(entity, d, round_money(subtotal * rate, fc), cost_center, vi_id, rng)
        take_discount = bool(vendor.discount_pct) and rng.random() < 0.8
        planned = d + timedelta(days=vendor.discount_days) if take_discount else due
        if vendor.late_payer_flag:
            planned += timedelta(days=rng.randint(15, 40))
        self.open[vi_id] = OpenPayable(inv, vendor, total, -ap_functional, max(planned, received), take_discount)
        # Duplicate submission of the same supplier invoice 5-20 days later.
        if duplicate_of is None and not vendor.is_intercompany and rng.random() < 0.005:
            self.vendor_invoice(
                entity,
                cat,
                d,
                None,
                rng,
                vendor=vendor,
                po=po,
                lines=[(p, desc, q, u, c) for _, p, desc, q, u, _, _, c in line_rows],
                cost_center=cost_center,
                account_override=account_override,
                duplicate_of=inv,
            )
        return inv

    # ------------------------------------------------------------------------------- payment runs
    def payment_run(self, entity_id: str, run_date: date) -> None:
        ctx = self.ctx
        horizon = run_date + timedelta(days=6)
        groups: dict[tuple[int, str], list[OpenPayable]] = {}
        for op in list(self.open.values()):
            if op.invoice["entity_id"] != entity_id or op.remaining <= 0 or op.planned_pay_date > horizon:
                continue
            if op.invoice["received_date"] > run_date:
                continue
            groups.setdefault((op.vendor.vendor_id, op.invoice["currency"]), []).append(op)
        for (_, ccy), items in sorted(groups.items()):
            vendor = items[0].vendor
            fc = ctx.entities[entity_id].functional_currency
            cc = ctx.org.cc(entity_id, "D17")
            counter, discounts, total_cash = [], [], ZERO
            for op in items:
                disc = ZERO
                within = op.take_discount and run_date <= op.invoice["invoice_date"] + timedelta(
                    days=(vendor.discount_days or 0) + 2
                )
                if within:
                    disc = round_money(op.invoice["subtotal"] * vendor.discount_pct / 100, ccy)
                ap = "2050" if vendor.is_intercompany else "2000"
                counter.append(
                    Line(
                        ap,
                        op.remaining,
                        ccy,
                        op.remaining_functional,
                        cc,
                        counterparty_entity_id=vendor.ic_entity_id,
                        description=f"Pay {op.invoice['vendor_invoice_number']}",
                    )
                )
                if disc:
                    counter.append(
                        Line(
                            "8300",
                            -disc,
                            ccy,
                            -round_money(disc * ctx.fx.spot(run_date, ccy, fc), fc),
                            cc,
                            description="Early payment discount",
                        )
                    )
                discounts.append(disc)
                total_cash += op.remaining - disc
            ctx.treasury.ensure_funds(entity_id, run_date, ccy, total_cash)
            ptype = "INTERCOMPANY_SETTLEMENT" if vendor.is_intercompany else "VENDOR_PAYMENT"
            payment = ctx.treasury.pay(
                entity_id,
                run_date,
                "OUTBOUND",
                ptype,
                ccy,
                total_cash,
                counter,
                counterparty_type="VENDOR",
                counterparty_id=str(vendor.vendor_id),
                counterparty_name=vendor.name,
                cost_center_id=cc,
                journal_type="AP_PAYMENT",
            )
            for op, disc in zip(items, discounts, strict=True):
                ctx.sink.emit(
                    "erp.payment_allocations",
                    {
                        "allocation_id": ctx.ids.next("allocation"),
                        "payment_id": payment["payment_id"],
                        "document_type": "VENDOR_INVOICE",
                        "document_id": op.invoice["vendor_invoice_id"],
                        "allocation_date": run_date,
                        "currency": ccy,
                        "allocated_amount": op.remaining - disc,
                        "discount_amount": disc,
                        "functional_amount_relieved": op.remaining_functional,
                        "created_at": payment["created_at"],
                        "updated_at": payment["created_at"],
                    },
                )
                op.invoice = dict(
                    op.invoice, outstanding_amount=ZERO, payment_status="PAID", updated_at=at(run_date, 18)
                )
                ctx.sink.emit("erp.vendor_invoices", op.invoice)
                if vendor.is_intercompany:
                    ctx.intercompany.on_buyer_payment(op.invoice, run_date, op.remaining - disc)
                op.remaining = ZERO
                op.remaining_functional = ZERO
                del self.open[op.invoice["vendor_invoice_id"]]
