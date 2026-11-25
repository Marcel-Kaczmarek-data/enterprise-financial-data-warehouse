-- Rate publications that must never be used for conversion, kept for audit of rate history:
-- non-positive values (quarantined) and publications superseded by a later correction.
with raw_rates as (
    select *
    from {{ source('fx', 'exchange_rates') }}
),

ranked as (
    select
        rate_date,
        source_currency,
        target_currency,
        rate_type,
        exchange_rate,
        publication_timestamp,
        _source_file as source_file,
        row_number() over (
            partition by rate_date, source_currency, target_currency, rate_type
            order by case when exchange_rate > 0 then 0 else 1 end, publication_timestamp desc
        ) as valid_rank
    from raw_rates
)

select
    *,
    case
        when exchange_rate is null or exchange_rate <= 0 then 'INVALID_NON_POSITIVE_RATE'
        else 'SUPERSEDED_BY_CORRECTION'
    end as quarantine_reason
from ranked
where exchange_rate is null or exchange_rate <= 0 or valid_rank > 1
