{#- Use the configured layer schema verbatim (finance_staging, finance_core, ...) in every target,
    so DuckDB and Snowflake share identical, predictable names. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
