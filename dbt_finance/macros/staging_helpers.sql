{#- Latest version per business key from an append-only raw table.
    Deterministic tie-breaks: newest updated_at, then latest extraction, then manifest key. -#}
{% macro dedupe_latest(relation, key_columns, version_column='updated_at') -%}
    select *
    from {{ relation }}
    qualify row_number() over (
        partition by {{ key_columns | join(', ') }}
        order by {{ version_column }} desc, _extracted_at desc, _manifest_key desc
    ) = 1
{%- endmacro %}

{#- Ingestion lineage columns carried from raw into every staging model. -#}
{% macro ingestion_lineage() -%}
    _batch_id as ingestion_batch_id,
    _source_system as source_system_code,
    _source_file as source_file,
    _extracted_at as extracted_at,
    _loaded_at as raw_loaded_at
{%- endmacro %}

{% macro to_money(expr) -%} cast({{ expr }} as decimal(19, 4)) {%- endmacro %}
{% macro to_rate(expr) -%} cast({{ expr }} as decimal(24, 10)) {%- endmacro %}
{% macro clean_code(expr) -%} upper(trim({{ expr }})) {%- endmacro %}
{% macro to_utc(expr) -%} cast({{ expr }} as timestamp with time zone) {%- endmacro %}
