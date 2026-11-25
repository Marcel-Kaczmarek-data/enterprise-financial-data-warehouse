-- Open financial exceptions for the latest period, grouped the way a close checklist is worked.
with latest as (
    select max(fiscal_period) as fiscal_period
    from finance_marts.mart_financial_exceptions
)

select
    e.exception_domain,
    e.exception_type,
    e.severity,
    count(*) as items,
    round(sum(abs(e.discrepancy_amount)), 2) as absolute_discrepancy,
    min(e.explanation) as example_explanation
from finance_marts.mart_financial_exceptions as e
inner join latest as l on e.fiscal_period = l.fiscal_period
group by e.exception_domain, e.exception_type, e.severity
order by
    case e.severity when 'CRITICAL' then 1 when 'WARNING' then 2 else 3 end,
    items desc;
