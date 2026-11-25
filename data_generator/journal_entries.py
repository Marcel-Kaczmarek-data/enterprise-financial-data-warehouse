"""Record-to-Report postings: opening balances, taxes, financing, allocations and manual journals.

Includes deliberate, documented anomalies that the warehouse must detect:
* two GL-only manual AR adjustments (no subledger document)  -> AR subledger reconciliation exception
* DRAFT manual journals that are never posted                 -> excluded from the ledger
* an erroneous accrual that is reversed and re-posted         -> reversal lineage
* a controlled period reopen with an audit adjustment         -> period status audit trail
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import Line, add_months, at, business_day, month_end, nth_business_day, period_of, rng_for
from finance_common.money import ZERO, round_money

REOPEN_WINDOWS = [("E06", "2023-06", "2023-08-02", "2023-08-03")]
MANUAL_AR_ADJUSTMENTS = [("E04", "2024-03-28", Decimal("18450.00")), ("E09", "2025-05-30", Decimal("27300.00"))]


class RecordToReport:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.loans: list[dict[str, Any]] = []
        self.tax_provisions: list[tuple[date, str, Decimal]] = []

    # ------------------------------------------------------------------------------ opening
    def opening_balances(self) -> None:
        ctx = self.ctx
        d = ctx.start
        share_capital: dict[str, Decimal] = {}
        children: dict[str, list[str]] = {}
        for e in ctx.entity_list:
            if e.parent_entity_id:
                children.setdefault(e.parent_entity_id, []).append(e.entity_id)

        # Children first (share capital determines the parent's investment).
        def depth(e: Any) -> int:
            n, p = 0, e.parent_entity_id
            while p:
                n, p = n + 1, ctx.entities[p].parent_entity_id
            return n

        order = sorted(ctx.entity_list, key=lambda e: -depth(e))  # deepest subsidiaries first
        for e in order:
            eid, fc = e.entity_id, e.functional_currency
            rng = rng_for(ctx.seed, "opening", eid)
            driver = ctx.cost_driver_eur(eid, d) * ctx.fx.spot(d, "EUR", fc)
            cc = ctx.org.cc(eid, "D17")
            lines: list[Line] = []
            for ba_id in ctx.treasury.by_entity[eid]:
                acc = ctx.treasury.accounts[ba_id]
                purpose = acc.row["account_purpose"]
                if acc.currency == fc:
                    amt = round_money(
                        driver * Decimal({"OPERATING": "3.0", "COLLECTIONS": "0.4", "PAYROLL": "0.05"}[purpose]), fc
                    )
                    f = amt
                else:
                    amt = round_money(Decimal(60000) * ctx.fx.spot(d, "EUR", acc.currency), acc.currency)
                    f = round_money(amt * ctx.fx.spot(d, acc.currency, fc), fc)
                lines.append(Line("1010", amt, acc.currency, f, cc, account_variant=ba_id, description="Opening cash"))
                acc.gl_fc_balance += amt
                acc.gl_functional += f
                acc.opening_bank_balance = amt
            if e.entity_type == "OPERATING":
                inv = round_money(driver * Decimal("0.45"), fc)
                lines.append(Line("1200", inv, fc, None, cc, description="Opening inventory"))
            ppe_cost, acc_dep = ctx.assets.opening_register(e, round_money(driver * Decimal("5"), fc), rng)
            lines += [
                Line("1500", ppe_cost, fc, None, cc, description="Opening PP&E cost"),
                Line("1590", -acc_dep, fc, None, cc, description="Opening accumulated depreciation"),
                Line("1600", round_money(driver * Decimal("0.3"), fc), fc, None, cc, description="Deposits"),
            ]
            for child in children.get(eid, []):
                c = ctx.entities[child]
                inv_amt = round_money(share_capital[child] * ctx.fx.spot(d, c.functional_currency, fc), fc)
                lines.append(
                    Line(
                        "1700",
                        inv_amt,
                        fc,
                        None,
                        cc,
                        counterparty_entity_id=child,
                        description=f"Investment in {child}",
                    )
                )
            sc = (
                round_money(driver * Decimal("2"), fc)
                if e.entity_type in ("OPERATING", "SHARED_SERVICES")
                else round_money(
                    sum((ln.functional or ln.amount for ln in lines if ln.group_code == "1700"), ZERO) + driver * 2, fc
                )
            )
            share_capital[eid] = sc
            parent = e.parent_entity_id
            lines.append(Line("3000", -sc, fc, None, cc, counterparty_entity_id=parent, description="Share capital"))
            if e.entity_type == "OPERATING" and e.sales_weight >= 1.0:
                principal = round_money(driver * Decimal("3"), fc)
                lines.append(Line("2500", -principal, fc, None, cc, description="Opening long-term borrowing"))
                self._loan_row(e, principal, date(2019, 6, 30), Decimal(repr(round(rng.uniform(3.2, 5.2), 2))))
            total = sum((ln.functional if ln.functional is not None else ln.amount for ln in lines), ZERO)
            lines.append(Line("3100", -total, fc, None, cc, description="Opening retained earnings (plug)"))
            jid = ctx.ledger.post(
                eid,
                d,
                "OPENING",
                lines,
                source_system="MIGRATION",
                source_document_type="OPENING_BALANCE",
                source_document_id=f"OB-{eid}",
                reference_number=f"OB-{eid}-{d:%Y%m%d}",
                description="Opening balances (migration)",
                created_at=at(d, 1),
                created_by="migration",
            )
            agg: dict[tuple[str, str | None], Decimal] = {}
            for ln in lines:
                key = (ln.group_code, ln.account_variant)
                agg[key] = agg.get(key, ZERO) + (ln.functional if ln.functional is not None else ln.amount)
            for (code, variant), amt in agg.items():
                ctx.sink.emit(
                    "erp.opening_balances",
                    {
                        "entity_id": eid,
                        "account_id": ctx.coa.account_for(eid, code, variant),
                        "balance_date": d,
                        "functional_currency": fc,
                        "balance_amount": amt,
                        "journal_id": jid,
                        "created_at": at(d, 1),
                        "updated_at": at(d, 1),
                    },
                )

    def _loan_row(self, e: Any, principal: Decimal, drawdown: date, rate: Decimal) -> dict:
        loan = {
            "loan_id": len(self.loans) + 1,
            "entity_id": e.entity_id,
            "lender_name": "Northgate Commercial Bank",
            "currency": e.functional_currency,
            "principal_amount": principal,
            "annual_interest_rate_pct": rate,
            "drawdown_date": drawdown,
            "maturity_date": date(drawdown.year + 8, drawdown.month, 28),
            "is_long_term": True,
            "created_at": at(drawdown, 10),
            "updated_at": at(drawdown, 10),
            "_outstanding": principal,
        }
        self.loans.append(loan)
        self.ctx.sink.emit("erp.loans", {k: v for k, v in loan.items() if not k.startswith("_")})
        return loan

    # ---------------------------------------------------------------------------- monthly R2R
    def month(self, month_start: date) -> None:
        ctx = self.ctx
        m_end = month_end(month_start)
        rng = rng_for(ctx.seed, "r2r", month_start.isoformat())
        # Loan drawdowns (financing inflow).
        if month_start in (date(2023, 3, 1), date(2024, 9, 1)):
            for eid in ("E09", "E02") if month_start.year == 2023 else ("E06",):
                e = ctx.entities[eid]
                principal = round_money(
                    ctx.cost_driver_eur(eid, month_start) * ctx.fx.spot(month_start, "EUR", e.functional_currency) * 2,
                    e.functional_currency,
                )
                d = business_day(month_start + timedelta(days=9))
                loan = self._loan_row(e, principal, d, Decimal("4.85"))
                cc = ctx.org.cc(eid, "D18", "D17")
                ctx.treasury.pay(
                    eid,
                    d,
                    "INBOUND",
                    "LOAN_DRAWDOWN",
                    e.functional_currency,
                    principal,
                    [Line("2500", -principal, e.functional_currency, None, cc, description="Loan drawdown")],
                    ba_id=ctx.treasury.account(eid, e.functional_currency, "OPERATING"),
                    counterparty_type="LENDER",
                    counterparty_name=loan["lender_name"],
                    cost_center_id=cc,
                    journal_type="LOAN",
                )
        # Interest (monthly) and principal repayment (quarterly).
        for loan in self.loans:
            if loan["_outstanding"] <= 0 or loan["drawdown_date"] >= month_start:
                continue
            eid, fc = loan["entity_id"], loan["currency"]
            cc = ctx.org.cc(eid, "D18", "D17")
            d = business_day(m_end, forward=False)
            interest = round_money(loan["_outstanding"] * loan["annual_interest_rate_pct"] / 100 / 12, fc)
            op = ctx.treasury.account(eid, fc, "OPERATING")
            ctx.treasury.pay(
                eid,
                d,
                "OUTBOUND",
                "INTEREST_PAYMENT",
                fc,
                interest,
                [Line("8100", interest, fc, None, cc, description="Loan interest")],
                ba_id=op,
                counterparty_type="LENDER",
                counterparty_name=loan["lender_name"],
                cost_center_id=cc,
                journal_type="LOAN",
                reference=f"INT-L{loan['loan_id']}-{d:%Y%m}",
            )
            if month_start.month % 3 == 0:
                repay = min(loan["_outstanding"], round_money(loan["principal_amount"] / 28, fc))
                ctx.treasury.pay(
                    eid,
                    d,
                    "OUTBOUND",
                    "LOAN_REPAYMENT",
                    fc,
                    repay,
                    [Line("2500", repay, fc, None, cc, description="Loan principal repayment")],
                    ba_id=op,
                    counterparty_type="LENDER",
                    counterparty_name=loan["lender_name"],
                    cost_center_id=cc,
                    journal_type="LOAN",
                    reference=f"PRN-L{loan['loan_id']}-{d:%Y%m}",
                )
                loan["_outstanding"] -= repay
        # Scheduled payroll tax remittances and income tax payments.
        due = [s for s in ctx.scheduled if s[0] <= m_end]
        ctx.scheduled = [s for s in ctx.scheduled if s[0] > m_end]
        for d, kind, eid, amount, ref in sorted(due):
            fc = ctx.entities[eid].functional_currency
            cc = ctx.org.cc(eid, "D17")
            code = {"PAYROLL_TAX": "2210", "INCOME_TAX": "2220"}[kind]
            ctx.treasury.pay(
                eid,
                d,
                "OUTBOUND",
                "TAX_PAYMENT",
                fc,
                amount,
                [Line(code, amount, fc, None, cc, description=f"{kind.replace('_', ' ').title()} remittance")],
                ba_id=ctx.treasury.account(eid, fc, "OPERATING"),
                counterparty_type="TAX_AUTHORITY",
                counterparty_name="Tax authority",
                cost_center_id=cc,
                journal_type="TAX_PAYMENT",
                reference=f"TAX-{ref}",
                method="TAX_TRANSFER",
            )
        # IT cost allocation from the IT cost center to all cost centers of the entity by headcount.
        for e in ctx.entity_list:
            it_cc = ctx.org.cc_by_entity_dept.get((e.entity_id, "D21"))
            if not it_cc or e.entity_type == "SHARED_SERVICES":
                continue
            pool = ctx.ledger.pl_by_key.get((e.entity_id, period_of(month_start), "6100", it_cc), ZERO)
            if pool <= 0:
                continue
            targets = [c for c in ctx.org.entity_cost_centers[e.entity_id] if c != it_cc]
            weights = [Decimal(max(1, len(ctx.payroll.by_cc.get(c, [])))) for c in targets]
            wsum = sum(weights, ZERO)
            alloc = round_money(pool * Decimal("0.8"), e.functional_currency)
            shares = [round_money(alloc * w / wsum, e.functional_currency) for w in weights]
            shares[0] += alloc - sum(shares, ZERO)
            lines = [Line("6100", -alloc, e.functional_currency, None, it_cc, description="IT cost allocation out")]
            lines += [
                Line("6100", s, e.functional_currency, None, c, description="IT cost allocation in")
                for c, s in zip(targets, shares, strict=True)
                if s
            ]
            ctx.ledger.post(
                e.entity_id,
                m_end,
                "ALLOCATION",
                lines,
                source_document_type="ALLOCATION_RUN",
                source_document_id=f"ALLOC-IT-{e.entity_id}-{period_of(month_start)}",
                reference_number=f"ALLOC-IT-{e.entity_id}-{period_of(month_start)}",
                description="Monthly IT cost allocation by headcount",
                created_at=at(m_end, 21),
                created_by="close.automation",
            )
        # Erroneous accrual reversed and re-posted (one random operating entity, quarterly).
        if month_start.month % 3 == 2:
            e = rng.choice([x for x in ctx.entity_list if x.entity_type == "OPERATING"])
            fc = e.functional_currency
            cc = ctx.org.cc(e.entity_id, "D17")
            wrong = round_money(Decimal(rng.randint(20000, 60000)) * ctx.fx.spot(month_start, "EUR", fc), fc)
            right = round_money(wrong / 10, fc)  # decimal-place keying error
            d = month_start + timedelta(days=9)
            ref = f"MJ-{e.entity_id}-{d:%Y%m}-AUDITFEE"
            j1 = ctx.ledger.post(
                e.entity_id,
                d,
                "ADJUSTMENT",
                [
                    Line("6600", wrong, fc, None, cc, description="Accrued audit fees"),
                    Line("2100", -wrong, fc, None, cc, description="Accrued audit fees"),
                ],
                source_document_type="MANUAL_JOURNAL",
                source_document_id=ref,
                reference_number=ref,
                description="Accrued audit fees",
                created_by="gl.accountant",
            )
            ctx.ledger.post(
                e.entity_id,
                d + timedelta(days=2),
                "REVERSAL",
                [
                    Line("6600", -wrong, fc, None, cc, description="Reverse erroneous accrual"),
                    Line("2100", wrong, fc, None, cc, description="Reverse erroneous accrual"),
                ],
                source_document_type="MANUAL_JOURNAL",
                source_document_id=ref,
                reference_number=f"REV-{ref}",
                description="Reversal: amount keyed incorrectly",
                reversal_of=j1,
                created_by="gl.controller",
            )
            ctx.ledger.post(
                e.entity_id,
                d + timedelta(days=2),
                "ADJUSTMENT",
                [
                    Line("6600", right, fc, None, cc, description="Accrued audit fees (corrected)"),
                    Line("2100", -right, fc, None, cc, description="Accrued audit fees (corrected)"),
                ],
                source_document_type="MANUAL_JOURNAL",
                source_document_id=ref,
                reference_number=f"{ref}-C",
                description="Accrued audit fees (corrected)",
                created_by="gl.accountant",
            )
            # Draft journal that is never posted (must be excluded from the ledger).
            ctx.ledger.post(
                e.entity_id,
                d + timedelta(days=5),
                "ADJUSTMENT",
                [
                    Line("6400", right, fc, None, cc, description="Draft reclass"),
                    Line("2100", -right, fc, None, cc, description="Draft reclass"),
                ],
                source_document_type="MANUAL_JOURNAL",
                source_document_id=f"{ref}-DRAFT",
                reference_number=f"{ref}-DRAFT",
                description="Draft reclassification (not posted)",
                posting_status="DRAFT",
                created_by="gl.accountant",
            )
        # GL-only AR adjustments (deliberate subledger reconciliation exceptions).
        for eid, ds, amount_eur in MANUAL_AR_ADJUSTMENTS:
            d = date.fromisoformat(ds)
            if period_of(d) == period_of(month_start):
                fc = ctx.entities[eid].functional_currency
                amt = round_money(amount_eur * ctx.fx.spot(d, "EUR", fc), fc)
                cc = ctx.org.cc(eid, "D17")
                ctx.ledger.post(
                    eid,
                    d,
                    "ADJUSTMENT",
                    [
                        Line("1100", amt, fc, None, cc, description="Manual AR adjustment - pending subledger update"),
                        Line("4200", -amt, fc, None, cc, description="Manual AR adjustment - pending subledger update"),
                    ],
                    source_document_type="MANUAL_JOURNAL",
                    source_document_id=f"MJ-AR-{eid}-{d:%Y%m%d}",
                    reference_number=f"MJ-AR-{eid}-{d:%Y%m%d}",
                    description="Manual AR adjustment",
                    created_by="gl.accountant",
                )
        # Controlled reopen: audit adjustment posted into a previously closed period.
        for eid, period, opened, _closed in REOPEN_WINDOWS:
            od = date.fromisoformat(opened)
            if period_of(od) == period_of(month_start):
                fc = ctx.entities[eid].functional_currency
                y, m = map(int, period.split("-"))
                pd = month_end(date(y, m, 1))
                amt = round_money(Decimal("42000") * ctx.fx.spot(pd, "EUR", fc), fc)
                cc = ctx.org.cc(eid, "D17")
                ctx.ledger.post(
                    eid,
                    pd,
                    "ADJUSTMENT",
                    [
                        Line("6600", amt, fc, None, cc, description="Audit adjustment: unrecorded legal fees"),
                        Line("2100", -amt, fc, None, cc, description="Audit adjustment: unrecorded legal fees"),
                    ],
                    source_document_type="AUDIT_ADJUSTMENT",
                    source_document_id=f"AUD-{eid}-{period}",
                    reference_number=f"AUD-{eid}-{period}",
                    description="External audit adjustment (period reopened)",
                    created_at=at(od, 11),
                    created_by="gl.controller",
                )

    def quarter_end(self, month_start: date) -> None:
        """VAT settlement snapshot, income tax provision and holding dividend."""
        ctx = self.ctx
        m_end = month_end(month_start)
        q_months = [period_of(add_months(month_start, -i)) for i in range(3)]
        for e in ctx.entity_list:
            eid, fc = e.entity_id, e.functional_currency
            cc = ctx.org.cc(eid, "D17")
            # VAT: settle the balances accumulated so far on business day 20 of the next month.
            out_vat = ctx.ledger.balances[(eid, "2200")]
            in_vat = ctx.ledger.balances[(eid, "1400")]
            settle = business_day(
                nth_business_day(add_months(month_start, 1).year, add_months(month_start, 1).month, 15)
            )
            net = -(out_vat + in_vat)  # positive = payable to the tax authority
            if settle <= ctx.end and (out_vat or in_vat):
                lines = [
                    Line("2200", -out_vat, fc, None, cc, description="VAT return: output VAT"),
                    Line("1400", -in_vat, fc, None, cc, description="VAT return: input VAT"),
                ]
                ctx.vat_due.append((settle, eid, net, lines))
            # Income tax provision on positive quarterly pre-tax profit.
            pre_tax = -sum((ctx.ledger.pl_entity_period.get((eid, p), ZERO) for p in q_months), ZERO)
            if pre_tax > 0:
                tax = round_money(pre_tax * ctx.income_tax_rate / 100, fc)
                ctx.ledger.post(
                    eid,
                    m_end,
                    "TAX_PROVISION",
                    [
                        Line("9000", tax, fc, None, cc, description="Income tax provision"),
                        Line("2220", -tax, fc, None, cc, description="Income tax provision"),
                    ],
                    source_document_type="TAX_PROVISION",
                    source_document_id=f"CIT-{eid}-{period_of(m_end)}",
                    reference_number=f"CIT-{eid}-{period_of(m_end)}",
                    description="Quarterly income tax provision",
                    created_at=at(m_end, 21, 30),
                    created_by="tax.team",
                )
                pay = business_day(add_months(m_end, 2).replace(day=15))
                if pay <= ctx.end:
                    ctx.scheduled.append((pay, "INCOME_TAX", eid, tax, f"CIT-{eid}-{period_of(m_end)}"))

    def vat_settlements(self, until: date) -> None:
        ctx = self.ctx
        due = [v for v in ctx.vat_due if v[0] <= until]
        ctx.vat_due = [v for v in ctx.vat_due if v[0] > until]
        for d, eid, net, lines in due:
            fc = ctx.entities[eid].functional_currency
            cc = ctx.org.cc(eid, "D17")
            if net == 0:
                continue
            direction = "OUTBOUND" if net > 0 else "INBOUND"
            ctx.treasury.pay(
                eid,
                d,
                direction,
                "TAX_PAYMENT" if net > 0 else "TAX_REFUND",
                fc,
                abs(net),
                lines,
                ba_id=ctx.treasury.account(eid, fc, "OPERATING"),
                counterparty_type="TAX_AUTHORITY",
                counterparty_name="Tax authority",
                cost_center_id=cc,
                journal_type="VAT_SETTLEMENT",
                reference=f"VAT-{eid}-{d:%Y%m}",
                method="TAX_TRANSFER",
            )

    def annual_dividend(self, month_start: date) -> None:
        ctx = self.ctx
        if month_start.month != 5:
            return
        e = ctx.entities["E01"]
        prior = [f"{month_start.year - 1}-{m:02d}" for m in range(1, 13)]
        profit = -sum((ctx.ledger.pl_entity_period.get(("E01", p), ZERO) for p in prior), ZERO)
        if profit <= 0:
            return
        op = ctx.treasury.account("E01", "EUR", "OPERATING")
        cash = ctx.treasury.accounts[op].gl_fc_balance
        amount = round_money(min(profit * Decimal("0.5"), cash * Decimal("0.5")), "EUR")
        if amount <= 0:
            return
        d = business_day(month_start + timedelta(days=19))
        cc = ctx.org.cc("E01", "D18", "D17")
        ctx.treasury.pay(
            "E01",
            d,
            "OUTBOUND",
            "DIVIDEND",
            "EUR",
            amount,
            [Line("3100", amount, e.functional_currency, None, cc, description="Dividend to shareholders")],
            ba_id=op,
            counterparty_type="SHAREHOLDERS",
            counterparty_name="External shareholders",
            cost_center_id=cc,
            journal_type="DIVIDEND",
            reference=f"DIV-{month_start.year}",
        )
