{#- Double-entry assertion: the signed amount sums to zero within each group (exact by default). -#}
{% test sums_to_zero(model, column_name, group_by, tolerance=0) %}
select {{ group_by | join(', ') }}, sum({{ column_name }}) as imbalance
from {{ model }}
group by {{ group_by | join(', ') }}
having abs(sum({{ column_name }})) > {{ tolerance }}
{% endtest %}
