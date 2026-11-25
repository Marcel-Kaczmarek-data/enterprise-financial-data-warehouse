-- Latest VALID publication per (rate date, currency, rate type).
-- Convention: eur_to_currency = units of <currency> per 1 EUR, as published by the provider.
-- Corrections are re-publications with a later publication_timestamp; the latest valid one wins.
select
    rate_date,
    target_currency as currency,
    rate_type,
    exchange_rate as eur_to_currency,
    publication_timestamp,
    provider
from {{ ref('stg_fx__exchange_rates') }}
where source_currency = 'EUR'
qualify row_number() over (
    partition by rate_date, target_currency, rate_type
    order by publication_timestamp desc
) = 1
