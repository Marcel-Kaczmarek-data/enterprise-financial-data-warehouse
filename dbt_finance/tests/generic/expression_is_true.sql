{% test expression_is_true(model, expression, column_name=None, where_clause=None) %}
select *
from {{ model }}
where not ({{ expression }})
{% if where_clause %} and {{ where_clause }} {% endif %}
{% endtest %}
