"""Payroll system: employees, effective-dated job history, monthly payroll and expense claims.

Accounting per entity and pay period (summarised by cost center, as a payroll interface would):
* Accrual on pay date:  Dr 6000 gross, Dr 6050 employer contributions
                        Cr 2300 net pay + reimbursements, Cr 2210 withholding + employer contributions
* Expense claims:       Dr 6500 travel  Cr 2300 (reimbursed with the next payroll)
* Salary payment:       Dr 2300  Cr 1010 (one bulk bank transaction per payroll run)
* Tax remittance (15th of next month): Dr 2210  Cr 1010
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import Line, add_months, at, business_day, month_end, period_of, rng_for
from finance_common.money import ZERO, round_money

FIRST = [
    "Alex",
    "Maria",
    "Jonas",
    "Sofia",
    "Liam",
    "Emma",
    "Noah",
    "Mia",
    "Lucas",
    "Hana",
    "Arjun",
    "Yuki",
    "Chen",
    "Priya",
    "Oliver",
    "Elena",
    "Mateo",
    "Aisha",
    "Felix",
    "Ingrid",
    "Kenji",
    "Ravi",
    "Chloe",
    "Erik",
    "Nora",
]
LAST = [
    "Schmidt",
    "Martin",
    "Smith",
    "Tanaka",
    "Sharma",
    "Andersson",
    "Müller",
    "Dubois",
    "Brown",
    "Lee",
    "Murphy",
    "Rossi",
    "Nguyen",
    "Patel",
    "Kowalski",
    "Jensen",
    "Garcia",
    "Sato",
    "Wilson",
    "Moreau",
    "Fischer",
    "Kim",
]
GRADES = [("G1", 38000), ("G2", 48000), ("G3", 60000), ("G4", 75000), ("G5", 95000), ("G6", 125000), ("G7", 170000)]
COUNTRY_PAY = {
    "NL": 1.0,
    "DE": 1.05,
    "FR": 0.95,
    "IE": 1.0,
    "GB": 1.0,
    "CH": 1.45,
    "SE": 0.95,
    "US": 1.3,
    "CA": 1.0,
    "JP": 0.9,
    "SG": 1.05,
    "IN": 0.3,
}
TITLES = {
    "OPERATIONS": "Operations Specialist",
    "SALES": "Account Executive",
    "MARKETING": "Marketing Manager",
    "R&D": "Software Engineer",
    "G&A": "Business Analyst",
}
DEPT_HEADCOUNT_WEIGHT = {"SALES": 3.0, "OPERATIONS": 2.5, "R&D": 2.5, "MARKETING": 1.2, "G&A": 1.2}


@dataclass
class Employee:
    employee_id: int
    entity_id: str
    cost_center_id: str
    department_id: str
    grade_idx: int
    salary: Decimal  # annual, functional currency
    hire_date: date
    first: str
    last: str
    termination_date: date | None = None
    history: list[dict] = field(default_factory=list)


class Payroll:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.employees: list[Employee] = []
        self.by_cc: dict[str, list[Employee]] = defaultdict(list)
        self.pending_claims: dict[str, list[tuple[int, Decimal, str]]] = defaultdict(list)
        self.headcount_by_entity: dict[str, int] = defaultdict(int)
        self._next_id = 10000

    # --------------------------------------------------------------------------------- workforce
    def _hire(self, entity: Any, hire_date: date, rng, cc: str | None = None) -> Employee:
        ctx = self.ctx
        ccs = ctx.org.entity_cost_centers[entity.entity_id]
        if cc is None:
            weights = [DEPT_HEADCOUNT_WEIGHT[ctx.dept_area[ctx.org.cost_center_department[c]]] for c in ccs]
            cc = rng.choices(ccs, weights=weights)[0]
        grade_idx = min(6, max(0, int(rng.triangular(0, 6.99, 1.6))))
        base_eur = Decimal(GRADES[grade_idx][1]) * Decimal(repr(COUNTRY_PAY[entity.country]))
        salary = round_money(
            base_eur
            * Decimal(repr(rng.uniform(0.92, 1.12)))
            * ctx.fx.spot(max(hire_date, ctx.start), "EUR", entity.functional_currency),
            entity.functional_currency,
        )
        self._next_id += 1
        emp = Employee(
            self._next_id,
            entity.entity_id,
            cc,
            ctx.org.cost_center_department[cc],
            grade_idx,
            salary,
            hire_date,
            rng.choice(FIRST),
            rng.choice(LAST),
        )
        self._history(emp, hire_date, "HIRE")
        self.employees.append(emp)
        self.by_cc[cc].append(emp)
        return emp

    def _history(self, emp: Employee, eff: date, reason: str) -> None:
        if emp.history:
            emp.history[-1]["effective_to"] = eff - timedelta(days=1)
        area = self.ctx.dept_area[emp.department_id]
        emp.history.append(
            {
                "employee_id": emp.employee_id,
                "effective_from": eff,
                "effective_to": None,
                "entity_id": emp.entity_id,
                "department_id": emp.department_id,
                "cost_center_id": emp.cost_center_id,
                "job_title": ("Senior " if emp.grade_idx >= 4 else "") + TITLES[area],
                "grade": GRADES[emp.grade_idx][0],
                "annual_salary": emp.salary,
                "change_reason": reason,
                "created_at": at(eff - timedelta(days=7), 9),
                "updated_at": at(eff - timedelta(days=7), 9),
            }
        )

    def build_workforce(self, n_employees: int) -> None:
        ctx = self.ctx
        rng = rng_for(ctx.seed, "workforce")
        initial = int(n_employees * 0.62)
        entities = ctx.entity_list
        weights = [
            max(0.15, e.sales_weight)
            if e.entity_type == "OPERATING"
            else (0.35 if e.entity_type == "SHARED_SERVICES" else 0.12)
            for e in entities
        ]
        for _ in range(initial):
            e = rng.choices(entities, weights=weights)[0]
            self._hire(e, ctx.start - timedelta(days=rng.randint(30, 3000)), rng)
        self._hire_weights = weights
        self._target_total = n_employees

    def active(self, eid: str, d: date) -> list[Employee]:
        return [
            e
            for e in self.employees
            if e.entity_id == eid and e.hire_date <= d and (e.termination_date is None or e.termination_date >= d)
        ]

    def workforce_month(self, month_start: date) -> None:
        """Attrition, hiring, April salary review, promotions and transfers (effective-dated)."""
        ctx = self.ctx
        rng = rng_for(ctx.seed, "workforce", month_start.isoformat())
        months_total = len(ctx.months)
        remaining_months = max(1, months_total - ctx.months.index(month_start))
        active = [e for e in self.employees if e.termination_date is None]
        for emp in active:
            if rng.random() < 0.006:
                emp.termination_date = month_start + timedelta(days=rng.randint(0, 27))
                self._history(emp, emp.termination_date + timedelta(days=1), "TERMINATION")
                emp.history[-1]["effective_to"] = emp.history[-1]["effective_from"]
        missing = self._target_total - len(self.employees)
        hires = max(0, round(missing / remaining_months))
        for _ in range(hires):
            e = rng.choices(ctx.entity_list, weights=self._hire_weights)[0]
            self._hire(e, month_start + timedelta(days=rng.randint(0, 25)), rng)
        for emp in self.employees:
            if emp.termination_date is not None or emp.hire_date >= month_start:
                continue
            if month_start.month == 4:  # annual salary review
                emp.salary = round_money(
                    emp.salary * Decimal(repr(rng.uniform(1.015, 1.05))),
                    ctx.entities[emp.entity_id].functional_currency,
                )
                if rng.random() < 0.08 and emp.grade_idx < 6:
                    emp.grade_idx += 1
                    emp.salary = round_money(
                        emp.salary * Decimal("1.10"), ctx.entities[emp.entity_id].functional_currency
                    )
                    self._history(emp, month_start, "PROMOTION")
                else:
                    self._history(emp, month_start, "SALARY_REVIEW")
            elif rng.random() < 0.0025:
                ccs = ctx.org.entity_cost_centers[emp.entity_id]
                new_cc = rng.choice(ccs)
                if new_cc != emp.cost_center_id:
                    self.by_cc[emp.cost_center_id].remove(emp)
                    emp.cost_center_id = new_cc
                    emp.department_id = ctx.org.cost_center_department[new_cc]
                    self.by_cc[new_cc].append(emp)
                    self._history(emp, month_start, "TRANSFER")

    # ------------------------------------------------------------------------------------ payroll
    def run_month(self, entity: Any, month_start: date) -> None:
        ctx = self.ctx
        eid, fc = entity.entity_id, entity.functional_currency
        rng = rng_for(ctx.seed, "payroll", eid, month_start.isoformat())
        pay_date = business_day(date(month_start.year, month_start.month, 25), forward=False)
        period = period_of(month_start)
        employer_rate = ctx.employer_rates[entity.country]
        withholding = ctx.withholding_rate
        claims = self.pending_claims.pop(eid, [])
        claims_by_emp: dict[int, Decimal] = defaultdict(lambda: ZERO)
        for emp_id, amt, _ in claims:
            claims_by_emp[emp_id] += amt
        run_id = f"PR-{eid}-{period}"
        per_cc: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO, ZERO, ZERO])  # gross, er, wh, reimb
        employees = self.active(eid, pay_date)
        self.headcount_by_entity[eid] = len(employees)
        if not employees:
            return
        jid_placeholder: list[dict] = []
        for emp in employees:
            gross = round_money(emp.salary / 12, fc)
            if emp.hire_date > month_start or (emp.termination_date and emp.termination_date < month_end(month_start)):
                gross = round_money(gross * Decimal("0.5"), fc)
            er = round_money(gross * employer_rate / 100, fc)
            wh = round_money(gross * withholding / 100, fc)
            reimb = claims_by_emp.pop(emp.employee_id, ZERO)
            net = gross - wh + reimb
            row = {
                "payroll_line_id": self.ctx.ids.next("payroll_line"),
                "payroll_run_id": run_id,
                "employee_id": emp.employee_id,
                "entity_id": eid,
                "cost_center_id": emp.cost_center_id,
                "department_id": emp.department_id,
                "pay_period": period,
                "pay_date": pay_date,
                "currency": fc,
                "gross_salary": gross,
                "employee_tax_withheld": wh,
                "employer_contributions": er,
                "expense_reimbursement": reimb,
                "net_pay": net,
                "journal_id": None,
                "created_at": at(pay_date - timedelta(days=3), 8),
                "updated_at": at(pay_date - timedelta(days=3), 8),
            }
            jid_placeholder.append(row)
            acc = per_cc[emp.cost_center_id]
            acc[0] += gross
            acc[1] += er
            acc[2] += wh
            acc[3] += reimb
        # Claims of employees who left before the run are reimbursed to the general CC.
        for _emp_id, amt in claims_by_emp.items():
            per_cc[ctx.org.cc(eid, "D20", "D17")][3] += amt
        lines, net_total, tax_total = [], ZERO, ZERO
        for cc, (gross, er, wh, reimb) in sorted(per_cc.items()):
            if gross:
                lines.append(Line("6000", gross, fc, None, cc, description="Gross salaries"))
            if er:
                lines.append(Line("6050", er, fc, None, cc, description="Employer contributions"))
            net_total += gross - wh + reimb
            tax_total += wh + er
        lines += [
            Line(
                "2300",
                -(net_total - sum((v[3] for v in per_cc.values()), ZERO)),
                fc,
                None,
                ctx.org.cc(eid, "D20", "D17"),
                description="Net salaries payable",
            ),
            Line("2210", -tax_total, fc, None, ctx.org.cc(eid, "D20", "D17"), description="Payroll taxes payable"),
        ]
        jid = ctx.ledger.post(
            eid,
            pay_date,
            "PAYROLL",
            lines,
            source_system="PAYROLL",
            source_document_type="PAYROLL_RUN",
            source_document_id=run_id,
            reference_number=run_id,
            description=f"Payroll {period}",
            created_at=at(pay_date - timedelta(days=2), 9),
            created_by="payroll.interface",
        )
        for row in jid_placeholder:
            row["journal_id"] = jid
            ctx.sink.emit("payroll.payroll_transactions", row)
        # Salary payment (bulk) from the payroll account; fund it from the operating account first.
        pay_ba = (
            ctx.treasury.account(eid, fc, "PAYROLL")
            if any(ctx.treasury.accounts[a].row["account_purpose"] == "PAYROLL" for a in ctx.treasury.by_entity[eid])
            else ctx.treasury.account(eid, fc, "OPERATING")
        )
        op_ba = ctx.treasury.account(eid, fc, "OPERATING")
        if pay_ba != op_ba:
            ctx.treasury.transfer(eid, pay_date - timedelta(days=1), op_ba, pay_ba, net_total, "Payroll funding")
        cc = ctx.org.cc(eid, "D20", "D17")
        ctx.treasury.pay(
            eid,
            pay_date,
            "OUTBOUND",
            "PAYROLL",
            fc,
            net_total,
            [Line("2300", net_total, fc, None, cc, description="Salary payment")],
            ba_id=pay_ba,
            method="BULK_SEPA" if fc == "EUR" else "BULK_TRANSFER",
            counterparty_type="EMPLOYEES",
            counterparty_name="Payroll run",
            reference=f"SAL-{run_id}",
            cost_center_id=cc,
            journal_type="PAYROLL_PAYMENT",
            bank_lag_days=0,
        )
        # Remit withholding + employer contributions on the 15th of next month.
        remit = business_day(date(month_start.year, month_start.month, 15) + timedelta(days=31))
        remit = business_day(date(remit.year, remit.month, 15))
        if remit <= ctx.end:
            ctx.scheduled.append((remit, "PAYROLL_TAX", eid, tax_total, run_id))
        # New expense claims this month (reimbursed next month).
        for emp in employees:
            area = ctx.dept_area[emp.department_id]
            if rng.random() < (0.35 if area == "SALES" else 0.08):
                amt = round_money(Decimal(rng.randint(40, 1400)) * ctx.fx.spot(month_start, "EUR", fc), fc)
                claim_date = month_start + timedelta(days=rng.randint(0, 26))
                self.pending_claims[eid].append((emp.employee_id, amt, emp.cost_center_id))
                ctx.sink.emit(
                    "payroll.expense_claims",
                    {
                        "expense_claim_id": ctx.ids.next("claim"),
                        "employee_id": emp.employee_id,
                        "entity_id": eid,
                        "cost_center_id": emp.cost_center_id,
                        "claim_date": claim_date,
                        "expense_category": rng.choice(["TRAVEL", "MEALS", "LODGING", "MILEAGE"]),
                        "currency": fc,
                        "claim_amount": amt,
                        "claim_status": "APPROVED",
                        "reimbursed_in_period": period_of(add_months(month_start, 1)),
                        "journal_id": None,
                        "created_at": at(claim_date, 17),
                        "updated_at": at(claim_date, 17),
                    },
                )
        pending = self.pending_claims.get(eid, [])
        if pending:
            by_cc: dict[str, Decimal] = defaultdict(lambda: ZERO)
            for _, amt, cc_ in pending:
                by_cc[cc_] += amt
            total = sum(by_cc.values(), ZERO)
            cl = [Line("6500", a, fc, None, c, description="Approved expense claims") for c, a in sorted(by_cc.items())]
            cl.append(Line("2300", -total, fc, None, ctx.org.cc(eid, "D20", "D17"), description="Claims payable"))
            ctx.ledger.post(
                eid,
                month_end(month_start),
                "EXPENSE_CLAIMS",
                cl,
                source_system="PAYROLL",
                source_document_type="EXPENSE_CLAIM_BATCH",
                source_document_id=f"EC-{eid}-{period}",
                reference_number=f"EC-{eid}-{period}",
                description="Approved employee expense claims",
                created_at=at(month_end(month_start), 17),
                created_by="payroll.interface",
            )

    def finalize(self) -> None:
        for emp in self.employees:
            for h in emp.history:
                self.ctx.sink.emit("payroll.employee_job_history", h)
            cur = emp.history[-1]
            status = "TERMINATED" if emp.termination_date and emp.termination_date <= self.ctx.end else "ACTIVE"
            self.ctx.sink.emit(
                "payroll.employees",
                {
                    "employee_id": emp.employee_id,
                    "employee_number": f"EMP{emp.employee_id:06d}",
                    "first_name": emp.first,
                    "last_name": emp.last,
                    "entity_id": emp.entity_id,
                    "department_id": cur["department_id"],
                    "cost_center_id": cur["cost_center_id"],
                    "job_title": cur["job_title"],
                    "grade": cur["grade"],
                    "annual_salary": cur["annual_salary"],
                    "salary_currency": self.ctx.entities[emp.entity_id].functional_currency,
                    "hire_date": emp.hire_date,
                    "termination_date": emp.termination_date,
                    "employment_status": status,
                    "created_at": at(emp.hire_date - timedelta(days=10), 9),
                    "updated_at": cur["updated_at"],
                },
            )
