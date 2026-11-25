-- Profit and loss statement.
-- Grain: reporting_scope x entity_id x fiscal_period x statement_line (detail lines + subtotals).
--   STANDALONE   one entity, functional currency and EUR (period-average translation)
--   CONSOLIDATED entity_id = 'GROUP': sum of standalone EUR statements + elimination entries
-- Presentation sign: revenue and income positive, costs negative (amount = -signed debit-positive),
-- so subtotals are plain sums. EBITDA = operating profit before depreciation and amortization;
-- intercompany fees are included standalone and eliminated on consolidation.
with lines as (
    select statement_line, line_order, section from {{ ref('financial_statement_lines') }}
    where statement = 'INCOME_STATEMENT'
),

standalone as (
    select
        'STANDALONE' as reporting_scope,
        entity_id,
        fiscal_period,
        statement_line,
        -sum(movement_functional) as amount_functional,
        -sum(movement_reporting) as amount_reporting
    from {{ ref('fact_monthly_account_balances') }}
    where statement = 'INCOME_STATEMENT'
    group by 1, 2, 3, 4
),

eliminations as (
    select
        e.fiscal_period,
        g.statement_line,
        -sum(e.amount_reporting) as amount_reporting
    from {{ ref('int_intercompany_eliminations') }} as e
    inner join {{ ref('group_chart_of_accounts') }} as g on e.group_account_code = g.group_account_code
    where e.measure = 'MOVEMENT'
    group by 1, 2
),

consolidated as (
    select
        'CONSOLIDATED' as reporting_scope,
        'GROUP' as entity_id,
        fiscal_period,
        statement_line,
        cast(null as decimal(38, 4)) as amount_functional,
        sum(amount_reporting) as amount_reporting
    from (
        select fiscal_period, statement_line, amount_reporting from standalone
        union all
        select fiscal_period, statement_line, amount_reporting from eliminations
    ) as u
    group by 1, 2, 3, 4
),

detail as (
    select * from standalone
    union all
    select * from consolidated
),

-- complete grid so every statement shows every line (zero when no activity)
grid as (
    select d.reporting_scope, d.entity_id, d.fiscal_period, l.statement_line, l.line_order, l.section
    from (select distinct reporting_scope, entity_id, fiscal_period from detail) as d
    cross join lines as l
),

detail_full as (
    select
        g.reporting_scope, g.entity_id, g.fiscal_period, g.statement_line, g.line_order, g.section,
        false as is_subtotal,
        coalesce(d.amount_functional, case when g.reporting_scope = 'STANDALONE' then 0 end) as amount_functional,
        coalesce(d.amount_reporting, 0) as amount_reporting
    from grid as g
    left join detail as d
        on
            g.reporting_scope = d.reporting_scope and g.entity_id = d.entity_id
            and g.fiscal_period = d.fiscal_period and g.statement_line = d.statement_line
),

subtotal_defs as (
    select * from (values
        ('Total revenue', 40, 'Revenue', 'Revenue'),
        ('Gross profit', 60, 'Gross profit', 'Revenue|Cost of goods sold'),
        ('Total operating expenses', 180, 'Operating expenses', 'Operating expenses'),
        ('EBITDA', 200, 'EBITDA', 'Revenue|Cost of goods sold|Operating expenses'),
        ('Operating profit (EBIT)', 220, 'EBIT', 'Revenue|Cost of goods sold|Operating expenses|Depreciation and amortization'),
        ('Profit before tax', 400, 'Profit before tax',
         'Revenue|Cost of goods sold|Operating expenses|Depreciation and amortization|Financial items'),
        ('Net profit', 500, 'Net profit',
         'Revenue|Cost of goods sold|Operating expenses|Depreciation and amortization|Financial items|Income tax')
    ) as t (statement_line, line_order, section, included_sections)
),

subtotals as (
    select
        d.reporting_scope, d.entity_id, d.fiscal_period, s.statement_line, s.line_order, s.section,
        true as is_subtotal,
        sum(d.amount_functional) as amount_functional,
        sum(d.amount_reporting) as amount_reporting
    from detail_full as d
    inner join subtotal_defs as s on position('|' || d.section || '|' in '|' || s.included_sections || '|') > 0
    group by 1, 2, 3, 4, 5, 6
),

statement as (
    select * from detail_full
    union all
    select * from subtotals
)

select
    s.reporting_scope,
    s.entity_id,
    s.fiscal_period,
    cast(substr(s.fiscal_period, 1, 4) as integer) as fiscal_year,
    s.statement_line,
    s.line_order,
    s.section,
    s.is_subtotal,
    e.functional_currency,
    s.amount_functional,
    s.amount_reporting,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    sum(s.amount_reporting) over (
        partition by s.reporting_scope, s.entity_id, s.statement_line, substr(s.fiscal_period, 1, 4)
        order by s.fiscal_period rows between unbounded preceding and current row
    ) as ytd_amount_reporting,
    lag(s.amount_reporting) over (
        partition by s.reporting_scope, s.entity_id, s.statement_line order by s.fiscal_period
    ) as prior_month_amount_reporting,
    py.amount_reporting as prior_year_amount_reporting,
    {{ audit_columns() }}
from statement as s
left join {{ ref('dim_legal_entity') }} as e on s.entity_id = e.entity_id
left join statement as py
    on
        s.reporting_scope = py.reporting_scope and s.entity_id = py.entity_id
        and s.statement_line = py.statement_line
        and py.fiscal_period = cast(cast(substr(s.fiscal_period, 1, 4) as integer) - 1 as varchar) || substr(s.fiscal_period, 5)
