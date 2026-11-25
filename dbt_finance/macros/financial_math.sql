{#- NULL (not 0 and not an error) when the denominator is zero or missing. -#}
{% macro safe_divide(numerator, denominator) -%}
    case when {{ denominator }} is null or {{ denominator }} = 0 then null
         else cast({{ numerator }} as decimal(38, 10)) / {{ denominator }} end
{%- endmacro %}

{#- Group reporting amount: functional amount x rate (EUR per functional unit), rounded to cents. -#}
{% macro to_reporting(amount, rate) -%}
    round(cast({{ amount }} as decimal(38, 10)) * {{ rate }}, 2)
{%- endmacro %}

{#- Debit-positive signed amount -> natural presentation for a statement line (sign seed). -#}
{% macro presentation_amount(signed_amount, presentation_sign) -%}
    ({{ signed_amount }}) * ({{ presentation_sign }})
{%- endmacro %}

{#- Stable surrogate key across adapters (md5 of pipe-delimited, null-safe values). -#}
{% macro surrogate_key(columns) -%}
    md5({% for c in columns %}coalesce(cast({{ c }} as varchar), '_null_'){% if not loop.last %} || '|' || {% endif %}{% endfor %})
{%- endmacro %}

{#- Variance is favourable when actual > budget for revenue, actual < budget for costs. -#}
{% macro variance_is_favourable(actual, budget, is_revenue) -%}
    case when {{ is_revenue }} then {{ actual }} >= {{ budget }} else {{ actual }} <= {{ budget }} end
{%- endmacro %}
