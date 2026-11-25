{#- Transformation lineage columns added to core facts and marts. -#}
{% macro audit_columns() -%}
    cast('{{ invocation_id }}' as varchar) as dbt_invocation_id,
    cast('{{ var("financial_rule_version") }}' as varchar) as financial_rule_version,
    cast(current_timestamp as timestamp with time zone) as transformed_at
{%- endmacro %}

{#- on-run-end: persist every node result for pipeline observability (audit_pipeline_runs). -#}
{% macro log_dbt_results(results) %}
    {% if execute %}
        {% set ddl %}
            create schema if not exists finance_audit;
            create table if not exists finance_audit.audit_dbt_node_results (
                invocation_id varchar, node_unique_id varchar, resource_type varchar, status varchar,
                execution_seconds double, rows_affected bigint, failures bigint, message varchar,
                logged_at timestamp with time zone)
        {% endset %}
        {% do run_query(ddl) %}
        {% for r in results %}
            {% set msg = (r.message or '') | replace("'", "''") %}
            {% set ins %}
                insert into finance_audit.audit_dbt_node_results values (
                    '{{ invocation_id }}', '{{ r.node.unique_id }}', '{{ r.node.resource_type }}', '{{ r.status }}',
                    {{ r.execution_time or 0 }},
                    {{ (r.adapter_response or {}).get('rows_affected') or 'null' }},
                    {{ r.failures if r.failures is not none else 'null' }},
                    '{{ msg[:500] }}', current_timestamp)
            {% endset %}
            {% do run_query(ins) %}
        {% endfor %}
    {% endif %}
{% endmacro %}
