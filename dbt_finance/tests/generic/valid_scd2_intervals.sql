{#- SCD Type 2: no gaps or overlaps per business key, exactly one current row, valid_from < valid_to. -#}
{% test valid_scd2_intervals(model, business_key, valid_from='valid_from', valid_to='valid_to', current_flag='is_current') %}
with ordered as (
    select
        {{ business_key }} as bk, {{ valid_from }} as vf, {{ valid_to }} as vt, {{ current_flag }} as cur,
        lead({{ valid_from }}) over (partition by {{ business_key }} order by {{ valid_from }}) as next_vf
    from {{ model }}
)
select bk, vf, vt, 'overlap_or_gap' as issue from ordered where next_vf is not null and vt <> next_vf
union all
select bk, vf, vt, 'inverted_interval' from ordered where vt <= vf
union all
select bk, null, null, 'current_row_count' from ordered group by bk having sum(case when cur then 1 else 0 end) <> 1
{% endtest %}
