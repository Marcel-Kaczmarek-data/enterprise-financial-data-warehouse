-- Posted general-ledger lines enriched with header, group account mapping and reporting currency.
-- Grain: one posted journal line. DRAFT / unposted journals are excluded here by design.
-- Reporting translation per line (financial-rules.yaml):
--   * income statement lines and equity movements: period-average rate of the posting month,
--   * OPENING (migration) journals: spot rate at the opening date (historical rate).
-- Balance sheet monetary balances are re-translated at closing rates in fact_monthly_account_balances.
with lines as (
    select * from {{ ref('stg_erp__journal_lines') }}
),

headers as (
    select * from {{ ref('stg_erp__journal_headers') }}
),

accounts as (
    select * from {{ ref('int_account_mapping') }}
),

monthly_rates as (
    select * from {{ ref('int_fx_rates_monthly') }}
),

spot as (
    select * from {{ ref('int_fx_rates_daily') }}
),

joined as (
    select
        l.journal_line_id,
        l.journal_id,
        l.line_number,
        h.entity_id,
        h.journal_type,
        h.posting_date,
        h.transaction_date,
        h.fiscal_period,
        cast(substr(h.fiscal_period, 1, 4) as integer) as fiscal_year,
        h.source_system,
        h.source_document_type,
        h.source_document_id,
        h.reference_number,
        h.description as journal_description,
        h.reversal_of_journal_id,
        h.created_by,
        h.created_at as journal_created_at,
        l.account_id,
        a.local_account_code,
        a.local_account_name,
        a.bank_account_id,
        a.group_account_code,
        a.group_account_name,
        a.account_type,
        a.account_category,
        a.statement,
        a.statement_line,
        a.translation_method,
        a.mapping_version,
        l.cost_center_id,
        l.profit_center_id,
        l.department_id,
        l.counterparty_entity_id,
        l.line_description,
        l.debit_amount,
        l.credit_amount,
        l.functional_currency,
        l.functional_currency_amount as signed_amount_functional,
        l.transaction_currency,
        l.transaction_amount,
        l.exchange_rate as transaction_to_functional_rate,
        case
            when h.journal_type = 'OPENING' then s.rate_to_reporting
            else m.avg_rate_to_reporting
        end as functional_to_reporting_rate,
        case when h.journal_type = 'OPENING' then 'HISTORICAL_SPOT' else 'MONTH_AVG' end as reporting_rate_type,
        l.ingestion_batch_id,
        l.source_file as ingestion_source,
        greatest(l.updated_at, h.updated_at) as source_updated_at
    from lines as l
    inner join headers as h on l.journal_id = h.journal_id
    left join accounts as a on l.account_id = a.account_id
    left join monthly_rates as m on h.fiscal_period = m.fiscal_period and l.functional_currency = m.currency
    left join spot as s on h.posting_date = s.date_day and l.functional_currency = s.currency
    where h.posting_status = 'POSTED'
)

select
    *,
    '{{ var("group_reporting_currency") }}' as reporting_currency,
    {{ to_reporting('signed_amount_functional', 'functional_to_reporting_rate') }} as signed_amount_reporting
from joined
