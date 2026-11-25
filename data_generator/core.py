"""Generator core: deterministic RNG streams, typed Parquet sink, period calendar and the Ledger.

Every financial event in the simulation is posted through :class:`Ledger`, which enforces
double-entry balancing in the entity functional currency and refuses postings into closed periods.
"""

from __future__ import annotations

import calendar
import hashlib
import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from finance_common import contracts
from finance_common.money import ZERO, quantum, round_money, round_rate


class GeneratorError(RuntimeError):
    pass


class UnbalancedJournalError(GeneratorError):
    pass


class PeriodClosedError(GeneratorError):
    pass


def rng_for(seed: int, *parts: object) -> random.Random:
    """Independent, reproducible random stream per (seed, domain, ...) tuple."""
    digest = hashlib.sha256("|".join(map(str, (seed, *parts))).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def at(d: date, hour: int = 9, minute: int = 0, second: int = 0) -> datetime:
    return datetime.combine(d, time(hour % 24, minute % 60, second % 60), tzinfo=UTC)


def period_of(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def business_day(d: date, forward: bool = True) -> date:
    step = timedelta(days=1 if forward else -1)
    while d.weekday() >= 5:
        d += step
    return d


def nth_business_day(year: int, month: int, n: int) -> date:
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def months_between(start: date, end: date) -> list[date]:
    out, d = [], date(start.year, start.month, 1)
    while d <= end:
        out.append(d)
        d = add_months(d, 1)
    return out


# ------------------------------------------------------------------------------------------- sink
class Sink:
    """Buffers rows per contract table and writes typed Parquet part files.

    Rows are validated against the contract (exact column set). Mutable tables receive one row per
    version; the source seeder later materialises the state "as of" a cutoff timestamp.
    """

    def __init__(self, out_dir: Path, flush_rows: int = 250_000) -> None:
        self.out_dir = out_dir
        self.flush_rows = flush_rows
        self._buf: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._parts: dict[str, int] = defaultdict(int)
        self.counts: dict[str, int] = defaultdict(int)

    def emit(self, fqn: str, row: dict[str, Any]) -> None:
        contract = contracts.get(fqn)
        if set(row) != set(contract.column_names):
            missing = set(contract.column_names) - set(row)
            extra = set(row) - set(contract.column_names)
            raise GeneratorError(f"{fqn}: contract violation missing={missing} extra={extra}")
        self._buf[fqn].append(row)
        self.counts[fqn] += 1
        if len(self._buf[fqn]) >= self.flush_rows:
            self.flush(fqn)

    def flush(self, fqn: str) -> None:
        rows = self._buf.pop(fqn, [])
        if not rows:
            return
        contract = contracts.get(fqn)
        table = pa.Table.from_pylist(rows, schema=contract.arrow_schema())
        target = self.out_dir / contract.system / contract.name
        target.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, target / f"part-{self._parts[fqn]:05d}.parquet", compression="zstd")
        self._parts[fqn] += 1

    def close(self) -> dict[str, int]:
        for fqn in list(self._buf):
            self.flush(fqn)
        # Write empty files for contract tables that produced no rows so downstream schemas exist.
        for fqn, contract in contracts.TABLES.items():
            if self.counts.get(fqn, 0) == 0:
                target = self.out_dir / contract.system / contract.name
                target.mkdir(parents=True, exist_ok=True)
                pq.write_table(contract.arrow_schema().empty_table(), target / "part-00000.parquet")
        return dict(self.counts)


class Ids:
    def __init__(self) -> None:
        self._n: dict[str, int] = defaultdict(int)

    def next(self, name: str) -> int:
        self._n[name] += 1
        return self._n[name]


# ------------------------------------------------------------------------------------ fiscal periods
@dataclass
class PeriodCalendar:
    """Deterministic close calendar.

    Period P soft-closes on business day 4 of P+1 and closes on business day 8 of P+1 (time 18:00).
    Configured reopen windows temporarily reopen a closed period for controlled adjustments.
    """

    end_date: date
    reopen_windows: dict[tuple[str, str], tuple[datetime, datetime]] = field(default_factory=dict)

    def soft_close_at(self, period: str) -> datetime:
        y, m = map(int, period.split("-"))
        nxt = add_months(date(y, m, 1), 1)
        return at(nth_business_day(nxt.year, nxt.month, 4), 18)

    def close_at(self, period: str) -> datetime:
        y, m = map(int, period.split("-"))
        nxt = add_months(date(y, m, 1), 1)
        return at(nth_business_day(nxt.year, nxt.month, 8), 18)

    def status(self, entity_id: str, period: str, when: datetime) -> str:
        window = self.reopen_windows.get((entity_id, period))
        if window and window[0] <= when < window[1]:
            return "REOPENED"
        if when >= self.close_at(period):
            return "CLOSED"
        if when >= self.soft_close_at(period):
            return "SOFT_CLOSED"
        return "OPEN"

    def allowed(self, entity_id: str, posting_date: date, created_at: datetime, finance_journal: bool) -> bool:
        st = self.status(entity_id, period_of(posting_date), created_at)
        return st in ("OPEN", "REOPENED") or (st == "SOFT_CLOSED" and finance_journal)

    def resolve_posting_date(
        self, entity_id: str, desired: date, created_at: datetime, finance_journal: bool = False
    ) -> date:
        """Return the desired posting date if its period accepts postings, else the creation date."""
        if self.allowed(entity_id, desired, created_at, finance_journal):
            return desired
        fallback = created_at.date()
        if not self.allowed(entity_id, fallback, created_at, finance_journal):
            raise PeriodClosedError(f"{entity_id}: no open period for {desired} at {created_at}")
        return fallback


# ------------------------------------------------------------------------------------------ ledger
FINANCE_JOURNAL_TYPES = frozenset(
    {"ACCRUAL", "REVERSAL", "ADJUSTMENT", "DEPRECIATION", "FX_REVALUATION", "TAX_PROVISION", "PREPAID_AMORTIZATION"}
)


@dataclass
class Line:
    group_code: str
    amount: Decimal  # signed, debit-positive, in ``currency``
    currency: str
    functional: Decimal | None = None  # signed functional amount (computed when None)
    cost_center_id: str | None = None
    profit_center_id: str | None = None
    counterparty_entity_id: str | None = None
    account_variant: str | None = None  # e.g. "export" or a bank_account_id
    description: str | None = None
    rate: Decimal | None = None


class Ledger:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        # Running functional balances per (entity, group_code) – used by tax/VAT settlement logic.
        self.balances: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        # Period P&L movement per (entity, period) for tax provisions and budgets.
        self.pl_by_key: dict[tuple[str, str, str, str], Decimal] = defaultdict(lambda: ZERO)
        self.pl_entity_period: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)  # excl. income tax
        self.journal_count = 0
        self.line_count = 0

    def post(
        self,
        entity_id: str,
        posting_date: date,
        journal_type: str,
        lines: Iterable[Line],
        *,
        source_system: str = "ERP",
        source_document_type: str | None = None,
        source_document_id: str | None = None,
        reference_number: str | None = None,
        description: str | None = None,
        created_at: datetime | None = None,
        transaction_date: date | None = None,
        posting_status: str = "POSTED",
        reversal_of: int | None = None,
        created_by: str = "system",
    ) -> int:
        ctx = self.ctx
        ent = ctx.entities[entity_id]
        fc = ent.functional_currency
        created_at = created_at or at(posting_date, 10 + ctx.rng_misc.randint(0, 7), ctx.rng_misc.randint(0, 59))
        finance = journal_type in FINANCE_JOURNAL_TYPES
        if not ctx.periods.allowed(entity_id, posting_date, created_at, finance):
            raise PeriodClosedError(
                f"{entity_id} {journal_type}: period {period_of(posting_date)} closed at {created_at}"
            )
        lines = [ln for ln in lines if ln.amount != 0 or (ln.functional or 0) != 0]
        if len(lines) < 2:
            raise UnbalancedJournalError(f"{journal_type}: journal needs at least two lines")

        functional: list[Decimal] = []
        rates: list[Decimal] = []
        for ln in lines:
            if ln.functional is not None:
                f = round_money(ln.functional, fc)
                r = (
                    ln.rate
                    if ln.rate is not None
                    else (round_rate(abs(f / ln.amount)) if ln.amount != 0 else Decimal(1))
                )
            elif ln.currency == fc:
                f, r = round_money(ln.amount, fc), Decimal(1)
            else:
                r = ctx.fx.spot(posting_date, ln.currency, fc)
                f = round_money(ln.amount * r, fc)
            functional.append(f)
            rates.append(r)
        residual = -sum(functional, ZERO)
        if residual != 0:
            tolerance = quantum(fc) * len(lines)
            if abs(residual) > tolerance:
                raise UnbalancedJournalError(
                    f"{entity_id} {journal_type} {reference_number}: imbalance {residual} {fc}"
                )
            # Explicitly specified functional amounts (e.g. AR/AP control lines that the subledger
            # tracks) are authoritative: the rounding residual goes to the largest COMPUTED line.
            computed = [i for i, ln in enumerate(lines) if ln.functional is None] or list(range(len(lines)))
            idx = max(computed, key=lambda i: abs(functional[i]))
            functional[idx] += residual
        assert sum(functional, ZERO) == 0

        journal_id = ctx.ids.next("journal")
        header = {
            "journal_id": journal_id,
            "entity_id": entity_id,
            "journal_type": journal_type,
            "posting_date": posting_date,
            "transaction_date": transaction_date or posting_date,
            "fiscal_period": period_of(posting_date),
            "source_system": source_system,
            "source_document_type": source_document_type,
            "source_document_id": source_document_id,
            "reference_number": reference_number,
            "description": description,
            "posting_status": posting_status,
            "reversal_of_journal_id": reversal_of,
            "created_by": created_by,
            "created_at": created_at,
            "updated_at": created_at,
        }
        ctx.sink.emit("erp.journal_headers", header)
        for n, (ln, f, r) in enumerate(zip(lines, functional, rates, strict=True), start=1):
            account_id = ctx.coa.account_for(entity_id, ln.group_code, ln.account_variant)
            cc = ln.cost_center_id
            ctx.sink.emit(
                "erp.journal_lines",
                {
                    "journal_line_id": ctx.ids.next("journal_line"),
                    "journal_id": journal_id,
                    "line_number": n,
                    "account_id": account_id,
                    "debit_amount": f if f > 0 else ZERO,
                    "credit_amount": -f if f < 0 else ZERO,
                    "transaction_currency": ln.currency,
                    "transaction_amount": round_money(ln.amount, ln.currency),
                    "functional_currency": fc,
                    "functional_currency_amount": f,
                    "exchange_rate": r,
                    "cost_center_id": cc,
                    "profit_center_id": ln.profit_center_id,
                    "department_id": ctx.org.cost_center_department.get(cc) if cc else None,
                    "counterparty_entity_id": ln.counterparty_entity_id,
                    "line_description": ln.description,
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )
            if posting_status == "POSTED":
                self.balances[(entity_id, ln.group_code)] += f
                if ln.group_code[0] in "456789":
                    self.pl_by_key[(entity_id, period_of(posting_date), ln.group_code, cc or "")] += f
                    if ln.group_code != "9000":
                        self.pl_entity_period[(entity_id, period_of(posting_date))] += f
            self.line_count += 1
        self.journal_count += 1
        return journal_id
