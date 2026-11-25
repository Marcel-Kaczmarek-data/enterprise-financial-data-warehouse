-- Direct-method cash flow classification of every cash (group account 1010) GL line.
-- Classification uses the journal type, the ERP payment type and the supplier category:
--   operating:  customer collections/refunds, supplier payments, employee payments, tax,
--               bank charges, interest paid/received (policy: config/financial-rules.yaml)
--   investing:  capital expenditure (CAPEX suppliers), asset disposal proceeds
--   financing:  loan proceeds/repayments, dividends
--   intercompany settlements are operating at entity level and eliminated on consolidation
--   internal transfers and FX revaluation are not cash flows; their functional-currency
--   residuals (FX conversion differences, revaluation) form the "effect of exchange rates".
with cash as (
    select *
    from {{ ref('fact_general_ledger') }}
    where group_account_code = '1010' and journal_type <> 'OPENING'
),

payments as (
    select * from {{ ref('stg_erp__payments') }}
),

vendors as (
    select vendor_id, vendor_category from {{ ref('stg_erp__vendors') }}
),

classified as (
    select
        c.journal_line_id,
        c.journal_id,
        c.entity_id,
        c.fiscal_period,
        c.posting_date,
        c.journal_type,
        p.payment_type,
        c.signed_amount_functional,
        c.functional_currency,
        c.signed_amount_reporting,
        c.transaction_amount,
        c.transaction_currency,
        c.source_document_id,
        case
            when c.journal_type in ('BANK_TRANSFER') then 'INTERNAL_TRANSFER'
            when c.journal_type = 'FX_REVALUATION' then 'FX_EFFECT'
            when p.payment_type = 'INTERCOMPANY_SETTLEMENT' then 'OPERATING'
            when p.payment_type in ('CUSTOMER_RECEIPT', 'CUSTOMER_REFUND', 'PAYROLL', 'TAX_PAYMENT', 'TAX_REFUND')
                then 'OPERATING'
            when p.payment_type = 'VENDOR_PAYMENT' and v.vendor_category = 'CAPEX' then 'INVESTING'
            when p.payment_type = 'VENDOR_PAYMENT' then 'OPERATING'
            when p.payment_type = 'INTEREST_PAYMENT' then 'OPERATING'
            when p.payment_type = 'ASSET_SALE' then 'INVESTING'
            when p.payment_type in ('LOAN_DRAWDOWN', 'LOAN_REPAYMENT', 'DIVIDEND') then 'FINANCING'
            when c.journal_type = 'BANK' then 'OPERATING'
            else 'UNCLASSIFIED'
        end as cash_flow_section,
        case
            when c.journal_type = 'BANK_TRANSFER' then 'Internal transfers'
            when c.journal_type = 'FX_REVALUATION' then 'Revaluation of foreign currency cash'
            when p.payment_type = 'INTERCOMPANY_SETTLEMENT' then 'Intercompany settlements'
            when p.payment_type = 'CUSTOMER_RECEIPT' then 'Customer collections'
            when p.payment_type = 'CUSTOMER_REFUND' then 'Customer refunds'
            when p.payment_type = 'PAYROLL' then 'Employee payments'
            when p.payment_type in ('TAX_PAYMENT', 'TAX_REFUND') then 'Tax payments'
            when p.payment_type = 'VENDOR_PAYMENT' and v.vendor_category = 'CAPEX' then 'Purchase of property, plant and equipment'
            when p.payment_type = 'VENDOR_PAYMENT' then 'Supplier payments'
            when p.payment_type = 'INTEREST_PAYMENT' then 'Interest paid'
            when p.payment_type = 'ASSET_SALE' then 'Proceeds from asset disposals'
            when p.payment_type = 'LOAN_DRAWDOWN' then 'Proceeds from borrowings'
            when p.payment_type = 'LOAN_REPAYMENT' then 'Repayment of borrowings'
            when p.payment_type = 'DIVIDEND' then 'Dividends paid'
            when c.journal_type = 'BANK' and c.signed_amount_functional < 0 then 'Bank charges'
            when c.journal_type = 'BANK' then 'Interest received'
            else 'Unclassified'
        end as cash_flow_line
    from cash as c
    left join payments as p on c.journal_id = p.journal_id
    left join vendors as v
        on p.counterparty_type = 'VENDOR' and try_cast(p.counterparty_id as bigint) = v.vendor_id
)

select * from classified
