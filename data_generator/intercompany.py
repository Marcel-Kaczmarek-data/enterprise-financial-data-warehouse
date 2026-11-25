"""Intercompany charges between group entities (both sides recorded) and their settlement.

Seller: Dr 1150 AR-intercompany  Cr 4500 IC revenue            (counterparty = buyer)
Buyer:  Dr 6650 IC expense       Cr 2050 AP-intercompany        (counterparty = seller)
Settlement: buyer pays through the AP payment run; the seller receives the cash on the value date.

The buyer records the invoice 0-4 days after the seller, so some charges cross a month end and
create genuine intercompany timing differences for the reconciliation to detect.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import Line, at, business_day, rng_for
from finance_common.money import ZERO, round_money

FEE_RATES = {"MANAGEMENT_FEE": Decimal("0.025"), "IT_SERVICES": Decimal("0.040"), "REGIONAL_FEE": Decimal("0.015")}


def ic_relationships(entities: list[Any]) -> list[tuple[str, str, str]]:
    """(seller, buyer, invoice currency)."""
    rel = []
    for e in entities:
        if e.entity_type != "OPERATING":
            continue
        if e.parent_entity_id == "E01":
            rel.append(("E01", e.entity_id, "EUR"))
        if e.parent_entity_id == "E15":
            rel.append(("E15", e.entity_id, "USD"))
        if e.entity_id in ("E09", "E11"):
            rel.append(("E10", e.entity_id, "USD"))
    return rel


class Intercompany:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.open_seller: dict[int, dict[str, Any]] = {}  # buyer vendor_invoice_id -> seller state

    def charge_month(self, month_start: date) -> None:
        ctx = self.ctx
        for seller, buyer, ccy in ctx.ic_relationships:
            rng = rng_for(ctx.seed, "ic", seller, buyer, month_start.isoformat())
            service = {"E01": "MANAGEMENT_FEE", "E15": "REGIONAL_FEE", "E10": "IT_SERVICES"}[seller]
            base_eur = ctx.cost_driver_eur(buyer, month_start)
            amount = round_money(base_eur * FEE_RATES[service] * ctx.fx.spot(month_start, "EUR", ccy)
                                 * Decimal(repr(rng.uniform(0.95, 1.05))), ccy)
            d = business_day(date(month_start.year, month_start.month, 1) + timedelta(days=rng.randint(22, 26)))
            if d > ctx.end or amount <= 0:
                continue
            self._charge(seller, buyer, ccy, service, d, amount, rng)

    def _charge(self, seller: str, buyer: str, ccy: str, service: str, d: date, amount: Decimal, rng) -> None:
        ctx = self.ctx
        s_ent, b_ent = ctx.entities[seller], ctx.entities[buyer]
        ref = f"IC-{seller}-{buyer}-{d:%Y%m}"
        # Seller side: AR invoice to the group customer account.
        inv_id = ctx.ids.next("invoice")
        number = f"INV-{seller}-{d:%Y}-{inv_id:08d}"
        cc_s = ctx.org.cc(seller, "D17", "D24", "D21")
        created = at(d, 15)
        jid = ctx.ledger.post(seller, d, "IC_INVOICE", [
            Line("1150", amount, ccy, None, cc_s, counterparty_entity_id=buyer, description=f"IC {service} {buyer}"),
            Line("4500", -amount, ccy, None, cc_s, counterparty_entity_id=buyer, description=f"IC {service} revenue"),
        ], source_document_type="CUSTOMER_INVOICE", source_document_id=str(inv_id), reference_number=number,
            description=f"Intercompany {service.replace('_', ' ').lower()} to {buyer}", created_at=created)
        inv = {
            "invoice_id": inv_id, "invoice_number": number, "erp_customer_id": ctx.ic_customer_accounts[(seller, buyer)],
            "entity_id": seller, "sales_order_id": None, "invoice_date": d, "due_date": d + timedelta(days=30),
            "currency": ccy, "subtotal": amount, "tax_amount": ZERO, "invoice_amount": amount,
            "outstanding_amount": amount, "invoice_status": "OPEN", "is_intercompany": True,
            "counterparty_entity_id": buyer, "journal_id": jid, "is_deleted": False,
            "created_at": created, "updated_at": created,
        }
        ctx.sink.emit("erp.customer_invoices", inv)
        ctx.sink.emit("erp.customer_invoice_lines", {
            "invoice_line_id": ctx.ids.next("invoice_line"), "invoice_id": inv_id, "line_number": 1,
            "product_id": "IC-SERVICE", "quantity": Decimal(1), "unit_price": amount, "line_amount": amount,
            "tax_rate_pct": ZERO, "tax_amount": ZERO, "profit_center_id": None,
            "revenue_account_id": ctx.coa.account_for(seller, "4500"), "created_at": created, "updated_at": created,
        })
        seller_rate = ctx.fx.spot(d, ccy, s_ent.functional_currency)
        # Buyer side: supplier invoice from the group vendor (recorded 0-4 days later).
        buyer_date = d + timedelta(days=rng.choice([0, 0, 1, 2, 4]))
        vendor = ctx.ic_vendors[(seller, buyer)]
        cc_b = ctx.org.cc(buyer, "D17", "D24")
        vi = ctx.p2p.vendor_invoice(b_ent, "INTERCOMPANY", buyer_date, None, rng, vendor=vendor,
                                    lines=[(None, f"IC {service.replace('_', ' ').lower()}", Decimal(1), amount, cc_b)],
                                    cost_center=cc_b, account_override="6650")
        ic_id = ctx.ids.next("ic")
        ctx.sink.emit("erp.intercompany_transactions", {
            "ic_transaction_id": ic_id, "ic_reference": ref, "seller_entity_id": seller, "buyer_entity_id": buyer,
            "transaction_date": d, "service_type": service, "currency": ccy, "amount": amount,
            "seller_invoice_id": inv_id, "buyer_vendor_invoice_id": vi["vendor_invoice_id"] if vi else None,
            "created_at": created, "updated_at": created,
        })
        if vi:
            self.open_seller[vi["vendor_invoice_id"]] = {
                "invoice": inv, "remaining_functional": round_money(amount * seller_rate, s_ent.functional_currency),
            }

    def on_buyer_payment(self, vendor_invoice: dict[str, Any], pay_date: date, amount: Decimal) -> None:
        """Seller receives the settlement on the bank value date."""
        ctx = self.ctx
        state = self.open_seller.pop(vendor_invoice["vendor_invoice_id"], None)
        if state is None:
            return
        inv = state["invoice"]
        seller, ccy = inv["entity_id"], inv["currency"]
        value_date = business_day(pay_date + timedelta(days=1))
        if value_date > ctx.end:
            return
        cc = ctx.org.cc(seller, "D17", "D18")
        payment = ctx.treasury.pay(
            seller, value_date, "INBOUND", "INTERCOMPANY_SETTLEMENT", ccy, amount,
            [Line("1150", -amount, ccy, -state["remaining_functional"], cc,
                  counterparty_entity_id=inv["counterparty_entity_id"], description=f"IC settlement {inv['invoice_number']}")],
            counterparty_type="GROUP_ENTITY", counterparty_id=inv["counterparty_entity_id"],
            counterparty_name=ctx.entities[inv["counterparty_entity_id"]].entity_name, cost_center_id=cc,
            journal_type="AR_RECEIPT", bank_lag_days=0,
        )
        ctx.sink.emit("erp.payment_allocations", {
            "allocation_id": ctx.ids.next("allocation"), "payment_id": payment["payment_id"],
            "document_type": "CUSTOMER_INVOICE", "document_id": inv["invoice_id"], "allocation_date": value_date,
            "currency": ccy, "allocated_amount": amount, "discount_amount": ZERO,
            "functional_amount_relieved": state["remaining_functional"],
            "created_at": payment["created_at"], "updated_at": payment["created_at"],
        })
        ctx.sink.emit("erp.customer_invoices", dict(inv, outstanding_amount=ZERO, invoice_status="PAID",
                                                    updated_at=at(value_date, 18)))
