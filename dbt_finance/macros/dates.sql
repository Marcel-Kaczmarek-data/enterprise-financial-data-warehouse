{#- Adapter-dispatched date helpers (DuckDB local, Snowflake cloud). -#}

{% macro fiscal_period(date_expr) -%}{{ return(adapter.dispatch('fiscal_period', 'finance')(date_expr)) }}{%- endmacro %}
{% macro default__fiscal_period(date_expr) -%} strftime({{ date_expr }}, '%Y-%m') {%- endmacro %}
{% macro snowflake__fiscal_period(date_expr) -%} to_char({{ date_expr }}, 'YYYY-MM') {%- endmacro %}

{% macro period_start(period_expr) -%}{{ return(adapter.dispatch('period_start', 'finance')(period_expr)) }}{%- endmacro %}
{% macro default__period_start(period_expr) -%} cast({{ period_expr }} || '-01' as date) {%- endmacro %}
{% macro snowflake__period_start(period_expr) -%} to_date({{ period_expr }} || '-01') {%- endmacro %}

{% macro period_end(period_expr) -%} last_day({{ period_start(period_expr) }}) {%- endmacro %}

{% macro days_between(start_expr, end_expr) -%}{{ return(adapter.dispatch('days_between', 'finance')(start_expr, end_expr)) }}{%- endmacro %}
{% macro default__days_between(start_expr, end_expr) -%} date_diff('day', {{ start_expr }}, {{ end_expr }}) {%- endmacro %}
{% macro snowflake__days_between(start_expr, end_expr) -%} datediff('day', {{ start_expr }}, {{ end_expr }}) {%- endmacro %}

{% macro add_days(date_expr, n) -%}{{ return(adapter.dispatch('add_days', 'finance')(date_expr, n)) }}{%- endmacro %}
{% macro default__add_days(date_expr, n) -%} cast({{ date_expr }} + to_days(cast({{ n }} as integer)) as date) {%- endmacro %}
{% macro snowflake__add_days(date_expr, n) -%} dateadd('day', {{ n }}, {{ date_expr }}) {%- endmacro %}

{#- Inclusive calendar date spine. -#}
{% macro date_spine(start_date, end_date) -%}{{ return(adapter.dispatch('date_spine', 'finance')(start_date, end_date)) }}{%- endmacro %}
{% macro default__date_spine(start_date, end_date) -%}
    select cast(d as date) as date_day
    from generate_series(cast({{ start_date }} as date), cast({{ end_date }} as date), interval 1 day) as t(d)
{%- endmacro %}
{% macro snowflake__date_spine(start_date, end_date) -%}
    select dateadd('day', seq4(), to_date({{ start_date }})) as date_day
    from table(generator(rowcount => 4000))
    qualify date_day <= to_date({{ end_date }})
{%- endmacro %}
