-- ISO currencies used by the group, with minor units consistent with financial-rules.yaml.
select
    currency_code,
    currency_name,
    minor_units,
    currency_code = '{{ var("group_reporting_currency") }}' as is_group_reporting_currency
from (values
    ('EUR', 'Euro', 2), ('GBP', 'Pound sterling', 2), ('USD', 'US dollar', 2), ('CAD', 'Canadian dollar', 2),
    ('JPY', 'Japanese yen', 0), ('SGD', 'Singapore dollar', 2), ('INR', 'Indian rupee', 2),
    ('CHF', 'Swiss franc', 2), ('SEK', 'Swedish krona', 2), ('CNY', 'Chinese yuan renminbi', 2)
) as t (currency_code, currency_name, minor_units)
