"""Treasury: house bank accounts, payments, bank statement feed, loans and FX cash management.

Every cash movement initiated by the company goes through :meth:`Treasury.pay`, which creates
(1) the ERP payment record, (2) the balanced GL journal and (3) the bank statement line with a
realistic value-date lag. Bank-originated items (fees, interest) are created by the bank first and
posted to the GL a few days later by the accountant.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import Line, at, business_day, period_of, rng_for
from finance_common.money import ZERO, round_money

BANKS = ["Northgate Commercial Bank", "Meridian Trust Bank", "Harbor Atlantic Bank", "Pacific Crest Bank"]


@dataclass
class BankAccountState:
    row: dict[str, Any]
    entity_id: str
    currency: str
    functional_currency: str
    bank_balance: Decimal = ZERO          # account currency, bank view (value-dated)
    gl_fc_balance: Decimal = ZERO         # account currency, GL view (posting-dated)
    gl_functional: Decimal = ZERO         # functional currency, GL view
    opening_bank_balance: Decimal = ZERO
    txns: list[dict[str, Any]] = field(default_factory=list)


class Treasury:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.rng = rng_for(ctx.seed, "treasury")
        self.accounts: dict[str, BankAccountState] = {}
        self.by_entity: dict[str, list[str]] = defaultdict(list)
        self.loans: list[dict[str, Any]] = []
        self._bank_seq = 0

    # ---------------------------------------------------------------------------------- master data
    def build_accounts(self) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        created = at(date(self.ctx.start.year - 1, 10, 20))
        n = 0
        for e in self.ctx.entity_list:
            fc = e.functional_currency
            plan = [(fc, "OPERATING")]
            if e.entity_type == "OPERATING" and e.sales_weight >= 1.0:
                plan.append((fc, "COLLECTIONS"))
            if e.entity_type in ("OPERATING", "SHARED_SERVICES"):
                plan.append((fc, "PAYROLL"))
            for ccy in ("EUR", "USD"):
                if ccy != fc and e.entity_type != "SHARED_SERVICES":
                    plan.append((ccy, "FX"))
            rows = []
            for ccy, purpose in plan:
                n += 1
                ba_id = f"BA{n:03d}"
                bank = BANKS[(n * 7) % len(BANKS)]
                row = {
                    "bank_account_id": ba_id, "entity_id": e.entity_id, "bank_name": bank,
                    "account_number_masked": f"{e.country}** **** **** {1000 + n * 37:04d}",
                    "currency": ccy, "account_purpose": purpose, "gl_account_id": 0,
                    "opened_date": date(2015, 1, 1), "created_at": created, "updated_at": created,
                }
                rows.append(row)
                self.accounts[ba_id] = BankAccountState(row, e.entity_id, ccy, fc)
                self.by_entity[e.entity_id].append(ba_id)
            out[e.entity_id] = rows
        return out

    def account(self, entity_id: str, currency: str, purpose: str | None = None) -> str:
        ids = [a for a in self.by_entity[entity_id] if self.accounts[a].currency == currency]
        if not ids:
            raise KeyError(f"{entity_id} has no bank account in {currency}")
        if purpose:
            for a in ids:
                if self.accounts[a].row["account_purpose"] == purpose:
                    return a
        return ids[0]

    def has_currency(self, entity_id: str, currency: str) -> bool:
        return any(self.accounts[a].currency == currency for a in self.by_entity[entity_id])

    # ---------------------------------------------------------------------------------- bank feed
    def bank_txn(self, ba_id: str, value_date: date, amount: Decimal, txn_type: str, reference: str | None,
                 description: str, counterparty: str | None) -> dict[str, Any]:
        self._bank_seq += 1
        acc = self.accounts[ba_id]
        row = {
            "bank_transaction_id": f"BT{self._bank_seq:09d}", "bank_account_id": ba_id,
            "transaction_date": value_date, "value_date": value_date, "transaction_type": txn_type,
            "currency": acc.currency, "amount": round_money(amount, acc.currency),
            "bank_reference": reference, "description": description, "counterparty_name": counterparty,
            "reconciliation_status": "BOOKED", "statement_id": f"{ba_id}-{value_date:%Y%m}",
            "created_at": at(value_date, 22), "updated_at": at(value_date, 22),
        }
        if value_date <= self.ctx.end:
            acc.txns.append(row)
        return row

    def _cash_gl(self, ba_id: str, amount_ccy: Decimal, functional: Decimal) -> None:
        acc = self.accounts[ba_id]
        acc.gl_fc_balance += amount_ccy
        acc.gl_functional += functional

    # ---------------------------------------------------------------------------------- payments
    def pay(
        self,
        entity_id: str,
        pay_date: date,
        direction: str,  # INBOUND | OUTBOUND
        payment_type: str,
        currency: str,
        amount: Decimal,  # positive, payment currency
        counter_lines: list[Line],
        *,
        ba_id: str | None = None,
        method: str = "WIRE",
        counterparty_type: str | None = None,
        counterparty_id: str | None = None,
        counterparty_name: str | None = None,
        bank_charge: Decimal = ZERO,
        reference: str | None = None,
        bank_lag_days: int | None = None,
        description: str | None = None,
        cost_center_id: str | None = None,
        journal_type: str | None = None,
        source_document_type: str = "PAYMENT",
        missing_bank_reference: bool = False,
    ) -> dict[str, Any]:
        ctx = self.ctx
        ent = ctx.entities[entity_id]
        fc = ent.functional_currency
        ba_id = ba_id or self.account(entity_id, currency)
        sign = Decimal(1) if direction == "INBOUND" else Decimal(-1)
        payment_id = ctx.ids.next("payment")
        reference = reference or f"PMT{payment_id:09d}"
        rate = ctx.fx.spot(pay_date, currency, fc)
        net_cash = amount - bank_charge if direction == "INBOUND" else amount + bank_charge
        cash_functional = round_money(sign * net_cash * rate, fc)
        lines = [Line("1010", sign * net_cash, currency, cash_functional, cost_center_id,
                      account_variant=ba_id, description=f"{payment_type} {reference}")]
        if bank_charge:
            lines.append(Line("6450", bank_charge, currency, round_money(bank_charge * rate, fc), cost_center_id,
                              description="Bank charge deducted"))
        lines += counter_lines
        residual = -sum((ln.functional if ln.functional is not None else
                         (ln.amount if ln.currency == fc else round_money(ln.amount * ctx.fx.spot(pay_date, ln.currency, fc), fc))
                         for ln in lines), ZERO)
        if residual != 0:
            # Realized FX difference between document (historical) value and settlement value.
            lines.append(Line("8200", ZERO, fc, residual, ctx.org.cc(entity_id, "D18", "D17"),
                              description="Realized FX gain/loss"))
        journal_id = ctx.ledger.post(
            entity_id, pay_date, journal_type or f"{payment_type}", lines,
            source_document_type=source_document_type, source_document_id=str(payment_id),
            reference_number=reference, description=description or f"{payment_type} {counterparty_name or ''}".strip(),
        )
        self._cash_gl(ba_id, sign * net_cash, cash_functional)
        payment = {
            "payment_id": payment_id, "payment_number": reference, "payment_date": pay_date,
            "entity_id": entity_id, "payment_direction": direction, "payment_type": payment_type,
            "payment_method": method, "currency": currency, "payment_amount": round_money(amount, currency),
            "functional_amount": round_money(amount * rate, fc), "bank_charge_amount": round_money(bank_charge, currency),
            "payment_status": "COMPLETED", "bank_account_id": ba_id, "bank_reference": reference,
            "counterparty_type": counterparty_type, "counterparty_id": counterparty_id, "journal_id": journal_id,
            "created_at": at(pay_date, 11), "updated_at": at(pay_date, 11),
        }
        ctx.sink.emit("erp.payments", payment)
        lag = bank_lag_days if bank_lag_days is not None else (
            self.rng.choice([0, 1, 1, 2]) if direction == "INBOUND" else self.rng.choice([0, 0, 1]))
        value_date = business_day(pay_date + timedelta(days=lag))
        self.bank_txn(ba_id, value_date, sign * net_cash, payment_type,
                      None if missing_bank_reference else reference,
                      f"{payment_type} {counterparty_name or ''}".strip(), counterparty_name)
        return payment

    def transfer(self, entity_id: str, d: date, from_ba: str, to_ba: str, amount_from: Decimal, purpose: str) -> None:
        """Internal transfer / FX conversion between two house accounts of the same entity."""
        ctx = self.ctx
        fc = ctx.entities[entity_id].functional_currency
        a, b = self.accounts[from_ba], self.accounts[to_ba]
        rate_from = ctx.fx.spot(d, a.currency, fc)
        f_out = round_money(amount_from * rate_from, fc)
        amount_to = round_money(amount_from * ctx.fx.spot(d, a.currency, b.currency), b.currency)
        f_in = round_money(amount_to * ctx.fx.spot(d, b.currency, fc), fc)
        cc = ctx.org.cc(entity_id, "D18", "D17")
        lines = [Line("1010", -amount_from, a.currency, -f_out, cc, account_variant=from_ba, description=purpose),
                 Line("1010", amount_to, b.currency, f_in, cc, account_variant=to_ba, description=purpose)]
        if f_in != f_out:
            lines.append(Line("8200", ZERO, fc, f_out - f_in, cc, description="FX conversion difference"))
        ref = f"TRF{ctx.ids.next('transfer'):08d}"
        ctx.ledger.post(entity_id, d, "BANK_TRANSFER", lines, source_document_type="BANK_TRANSFER",
                        source_document_id=ref, reference_number=ref, description=purpose)
        self._cash_gl(from_ba, -amount_from, -f_out)
        self._cash_gl(to_ba, amount_to, f_in)
        self.bank_txn(from_ba, d, -amount_from, "INTERNAL_TRANSFER", ref, purpose, "Own account")
        self.bank_txn(to_ba, d, amount_to, "INTERNAL_TRANSFER", ref, purpose, "Own account")

    def ensure_funds(self, entity_id: str, d: date, currency: str, needed: Decimal) -> None:
        """Pre-fund a foreign-currency account from the operating account before a payment."""
        ba = self.account(entity_id, currency)
        acc = self.accounts[ba]
        if acc.row["account_purpose"] != "FX" or acc.gl_fc_balance >= needed:
            return
        fc = self.ctx.entities[entity_id].functional_currency
        op = self.account(entity_id, fc, "OPERATING")
        shortfall_fc = (needed - acc.gl_fc_balance) * Decimal("1.10")
        amount_from = round_money(shortfall_fc * self.ctx.fx.spot(d, currency, fc), fc)
        self.transfer(entity_id, d, op, ba, amount_from, f"FX funding {currency}")

    # ------------------------------------------------------------------------- periodic treasury
    def month_end(self, entity_id: str, month_start: date, m_end: date) -> None:
        ctx = self.ctx
        fc = ctx.entities[entity_id].functional_currency
        cc = ctx.org.cc(entity_id, "D18", "D17")
        last_bd = business_day(m_end, forward=False)
        for ba_id in self.by_entity[entity_id]:
            acc = self.accounts[ba_id]
            # Monthly account fee (bank-originated, booked by accountant 1-4 days later).
            fee = round_money(Decimal(self.rng.randint(15, 60)) * ctx.fx.spot(last_bd, "EUR", acc.currency), acc.currency)
            self._bank_originated(acc, ba_id, last_bd, -fee, "BANK_FEE", "6450", "Monthly account maintenance fee", cc)
            # Interest on positive balances (0.6% p.a.).
            if acc.gl_fc_balance > 0:
                interest = round_money(acc.gl_fc_balance * Decimal("0.006") / 12, acc.currency)
                if interest > 0:
                    self._bank_originated(acc, ba_id, last_bd, interest, "INTEREST_CREDIT", "8000",
                                          "Credit interest", cc)
        # Sweep FX accounts above a buffer back to the operating account.
        op = self.account(entity_id, fc, "OPERATING")
        for ba_id in self.by_entity[entity_id]:
            acc = self.accounts[ba_id]
            if acc.row["account_purpose"] == "FX":
                buffer = round_money(Decimal(50000) * ctx.fx.spot(last_bd, "EUR", acc.currency), acc.currency)
                if acc.gl_fc_balance > buffer * 3:
                    self.transfer(entity_id, last_bd, ba_id, op, round_money(acc.gl_fc_balance - buffer, acc.currency),
                                  f"FX sweep {acc.currency} to {fc}")
        # Collections account sweep to operating account.
        for ba_id in self.by_entity[entity_id]:
            acc = self.accounts[ba_id]
            if acc.row["account_purpose"] == "COLLECTIONS" and acc.gl_fc_balance > 0:
                self.transfer(entity_id, last_bd, ba_id, op, round_money(acc.gl_fc_balance * Decimal("0.9"), fc),
                              "Cash concentration sweep")
        # Payroll account funding happens in payroll module; FX revaluation of foreign-currency cash:
        for ba_id in self.by_entity[entity_id]:
            acc = self.accounts[ba_id]
            if acc.currency == fc:
                continue
            closing = ctx.fx.month_end(period_of(m_end), acc.currency, fc)
            target = round_money(acc.gl_fc_balance * closing, fc)
            adj = target - acc.gl_functional
            if adj != 0:
                lines = [Line("1010", ZERO, acc.currency, adj, cc, account_variant=ba_id, rate=closing,
                              description=f"Revaluation {acc.currency} cash at closing rate"),
                         Line("8200", ZERO, fc, -adj, cc, description="Unrealized FX on cash")]
                ctx.ledger.post(entity_id, m_end, "FX_REVALUATION", lines, source_document_type="FX_REVALUATION",
                                source_document_id=f"{ba_id}-{period_of(m_end)}",
                                reference_number=f"REVAL-{ba_id}-{m_end:%Y%m}",
                                description="Month-end revaluation of foreign currency cash",
                                created_at=at(m_end, 20))
                acc.gl_functional += adj

    def _bank_originated(self, acc: BankAccountState, ba_id: str, d: date, amount: Decimal, txn_type: str,
                         counter_code: str, description: str, cc: str) -> None:
        ctx = self.ctx
        fc = acc.functional_currency
        txn = self.bank_txn(ba_id, d, amount, txn_type, None, description, acc.row["bank_name"])
        created = at(business_day(d + timedelta(days=self.rng.randint(1, 4))), 10)
        posting = ctx.periods.resolve_posting_date(acc.entity_id, d, created)
        f = round_money(amount * ctx.fx.spot(posting, acc.currency, fc), fc)
        lines = [Line("1010", amount, acc.currency, f, cc, account_variant=ba_id, description=description),
                 Line(counter_code, -amount, acc.currency, -f, cc, description=description)]
        ctx.ledger.post(acc.entity_id, posting, "BANK", lines, source_document_type="BANK_TRANSACTION",
                        source_document_id=txn["bank_transaction_id"], reference_number=txn["bank_transaction_id"],
                        description=description, created_at=created, transaction_date=d)
        self._cash_gl(ba_id, amount, f)

    # ------------------------------------------------------------------------------------- output
    def finalize(self) -> None:
        """Emit bank statement lines (with injected feed duplicates) and daily balances."""
        ctx = self.ctx
        rng = rng_for(ctx.seed, "bank-feed")
        for ba_id, acc in self.accounts.items():
            acc.txns.sort(key=lambda r: (r["value_date"], r["bank_transaction_id"]))
            balance = acc.opening_bank_balance
            by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
            for t in acc.txns:
                ctx.sink.emit("banking.bank_transactions", t)
                by_day[t["value_date"]] += t["amount"]
                # Duplicate debit by the bank (distinct id): a real bank error to be caught by recon.
                if t["amount"] < 0 and t["transaction_type"] == "VENDOR_PAYMENT" and rng.random() < 0.0015:
                    dup = dict(t)
                    self._bank_seq += 1
                    dup["bank_transaction_id"] = f"BT{self._bank_seq:09d}"
                    dup["description"] = (t["description"] or "") + " (duplicate debit)"
                    ctx.sink.emit("banking.bank_transactions", dup)
                    by_day[t["value_date"]] += t["amount"]
            d = ctx.start
            while d <= ctx.end:
                opening = balance
                balance = opening + by_day.get(d, ZERO)
                ctx.sink.emit("banking.account_balances", {
                    "bank_account_id": ba_id, "balance_date": d, "currency": acc.currency,
                    "opening_balance": opening, "closing_balance": balance,
                    "statement_id": f"{ba_id}-{d:%Y%m}", "created_at": at(d, 23), "updated_at": at(d, 23),
                })
                d += timedelta(days=1)

