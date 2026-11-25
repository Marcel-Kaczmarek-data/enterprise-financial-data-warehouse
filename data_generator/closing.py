"""Accounting period records and the audit trail of period status transitions."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from data_generator.core import UTC, add_months, at, month_end, period_of


def emit_periods(ctx: Any) -> None:
    horizon = datetime.combine(ctx.end, datetime.max.time(), tzinfo=UTC)
    change_id = 0
    for e in ctx.entity_list:
        for m in [*ctx.months, add_months(ctx.months[-1], 1)]:
            p = period_of(m)
            opened = at(add_months(m, -1), 0) if m > ctx.start else at(ctx.start, 0)
            events: list[tuple[datetime, str | None, str, str, str]] = [
                (opened, None, "OPEN", "system", "Period opened")
            ]
            soft, close = ctx.periods.soft_close_at(p), ctx.periods.close_at(p)
            events.append((soft, "OPEN", "SOFT_CLOSED", "close.automation", "Subledger cut-off"))
            events.append((close, "SOFT_CLOSED", "CLOSED", "financial.controller", "Close approved"))
            window = ctx.periods.reopen_windows.get((e.entity_id, p))
            if window:
                events.append((window[0], "CLOSED", "REOPENED", "group.controller", "Audit adjustment requested"))
                events.append((window[1], "REOPENED", "CLOSED", "group.controller", "Audit adjustment posted"))
            events = [ev for ev in events if ev[0] <= horizon]
            for ts, frm, to, by, reason in events:
                change_id += 1
                ctx.sink.emit(
                    "erp.period_status_changes",
                    {
                        "change_id": change_id,
                        "entity_id": e.entity_id,
                        "fiscal_period": p,
                        "from_status": frm,
                        "to_status": to,
                        "changed_at": ts,
                        "changed_by": by,
                        "reason": reason,
                        "created_at": ts,
                        "updated_at": ts,
                    },
                )
                ctx.sink.emit(
                    "erp.accounting_periods",
                    {  # one version per transition
                        "entity_id": e.entity_id,
                        "fiscal_period": p,
                        "fiscal_year": m.year,
                        "period_number": m.month,
                        "period_start": date(m.year, m.month, 1),
                        "period_end": month_end(m),
                        "period_status": to,
                        "status_changed_at": ts,
                        "status_changed_by": by,
                        "created_at": events[0][0],
                        "updated_at": ts,
                    },
                )
