# Source data contracts

Generated from `finance_common/contracts.py` by `scripts/generate_contract_docs.py` - do not edit by hand.
The same registry produces the generator's Parquet schemas, the PostgreSQL DDL of the simulated ERP,
schema validation during ingestion and the dbt staging models.

44 tables. Sensitivity classes: `PII`, `FINANCIAL_ACCOUNT`, `PAYROLL` (masked in Snowflake).

| System | Tables |
|---|---|
| `banking` | `bank_transactions`, `account_balances` |
| `budgeting` | `budget_plans` |
| `crm` | `customers`, `customer_history`, `opportunities`, `sales_orders`, `revenue_forecasts` |
| `erp` | `legal_entities`, `departments`, `cost_centers`, `profit_centers`, `products`, `accounts`, `account_mappings`, `customer_accounts`, `vendors`, `bank_accounts`, `accounting_periods`, `period_status_changes`, `journal_headers`, `journal_lines`, `opening_balances`, `customer_invoices`, `customer_invoice_lines`, `credit_notes`, `purchase_requisitions`, `purchase_orders`, `purchase_order_lines`, `goods_receipts`, `vendor_invoices`, `vendor_invoice_lines`, `payments`, `payment_allocations`, `fixed_assets`, `depreciation_schedule`, `tax_transactions`, `intercompany_transactions`, `loans` |
| `fx` | `exchange_rates` |
| `payroll` | `employees`, `employee_job_history`, `payroll_transactions`, `expense_claims` |

## `banking`

### `banking.bank_transactions`

Bank statement lines (signed: + inflow, - outflow).

- Primary key: `bank_transaction_id`  
- Delivery: `csv` · append-only · watermark `value_date`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `bank_transaction_id` | TEXT | no |  |  |
| `bank_account_id` | TEXT | no |  |  |
| `transaction_date` | DATE | no |  |  |
| `value_date` | DATE | no |  |  |
| `transaction_type` | TEXT | no |  |  |
| `currency` | TEXT | no |  |  |
| `amount` | NUMERIC(19,4) | no |  |  |
| `bank_reference` | TEXT | yes |  |  |
| `description` | TEXT | yes |  |  |
| `counterparty_name` | TEXT | yes |  |  |
| `reconciliation_status` | TEXT | no |  |  |
| `statement_id` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `banking.account_balances`

End-of-day balances reported by the bank.

- Primary key: `bank_account_id, balance_date`  
- Delivery: `json` · append-only · watermark `balance_date`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `bank_account_id` | TEXT | no |  |  |
| `balance_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `opening_balance` | NUMERIC(19,4) | no |  |  |
| `closing_balance` | NUMERIC(19,4) | no |  |  |
| `statement_id` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

## `budgeting`

### `budgeting.budget_plans`

Budget and forecast plan lines (sign: positive = planned amount in natural presentation).

- Primary key: `budget_id`  
- Delivery: `excel` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `budget_id` | TEXT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `fiscal_year` | BIGINT | no |  |  |
| `fiscal_period` | TEXT | no |  |  |
| `account_code` | TEXT | no |  |  |
| `department_id` | TEXT | no |  |  |
| `cost_center_id` | TEXT | no |  |  |
| `budget_version` | TEXT | no |  |  |
| `scenario` | TEXT | no |  |  |
| `budget_amount` | NUMERIC(19,4) | no |  |  |
| `currency` | TEXT | no |  |  |
| `approval_status` | TEXT | no |  |  |
| `approved_at` | TIMESTAMPTZ | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

## `crm`

### `crm.customers`

CRM customer master (current state).

- Primary key: `customer_id`  
- Delivery: `api` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `customer_id` | BIGINT | no |  |  |
| `customer_number` | TEXT | no |  |  |
| `customer_name` | TEXT | no |  |  |
| `segment` | TEXT | no |  |  |
| `industry` | TEXT | no |  |  |
| `country` | TEXT | no |  |  |
| `home_entity_id` | TEXT | no |  |  |
| `contact_email` | TEXT | yes | PII |  |
| `tax_id` | TEXT | yes | PII |  |
| `customer_status` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `crm.customer_history`

CRM field-history audit log for customers.

- Primary key: `customer_id, valid_from`  
- Delivery: `api` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `customer_id` | BIGINT | no |  |  |
| `valid_from` | TIMESTAMPTZ | no |  |  |
| `segment` | TEXT | no |  |  |
| `industry` | TEXT | no |  |  |
| `country` | TEXT | no |  |  |
| `customer_status` | TEXT | no |  |  |
| `change_reason` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `crm.opportunities`

Sales pipeline.

- Primary key: `opportunity_id`  
- Delivery: `api` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `opportunity_id` | BIGINT | no |  |  |
| `customer_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `opportunity_name` | TEXT | no |  |  |
| `stage` | TEXT | no |  |  |
| `amount` | NUMERIC(19,4) | no |  |  |
| `currency` | TEXT | no |  |  |
| `probability_pct` | NUMERIC(9,4) | no |  |  |
| `expected_close_date` | DATE | no |  |  |
| `closed_date` | DATE | yes |  |  |
| `is_won` | BOOLEAN | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `crm.sales_orders`

Sales orders.

- Primary key: `sales_order_id`  
- Delivery: `api` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `sales_order_id` | BIGINT | no |  |  |
| `order_number` | TEXT | no |  |  |
| `customer_id` | BIGINT | no |  |  |
| `opportunity_id` | BIGINT | yes |  |  |
| `entity_id` | TEXT | no |  |  |
| `order_date` | DATE | no |  |  |
| `delivery_date` | DATE | yes |  |  |
| `currency` | TEXT | no |  |  |
| `order_amount` | NUMERIC(19,4) | no |  |  |
| `order_status` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `crm.revenue_forecasts`

Monthly weighted pipeline snapshots.

- Primary key: `forecast_id`  
- Delivery: `api` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `forecast_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `forecast_month` | TEXT | no |  |  |
| `snapshot_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `pipeline_amount` | NUMERIC(19,4) | no |  |  |
| `weighted_amount` | NUMERIC(19,4) | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

## `erp`

### `erp.legal_entities`

Legal entity master and ownership hierarchy.

- Primary key: `entity_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `entity_id` | TEXT | no |  |  |
| `parent_entity_id` | TEXT | yes |  |  |
| `entity_name` | TEXT | no |  |  |
| `country` | TEXT | no |  |  |
| `functional_currency` | TEXT | no |  |  |
| `reporting_currency` | TEXT | no |  |  |
| `fiscal_calendar` | TEXT | no |  |  |
| `ownership_percentage` | NUMERIC(9,4) | no |  |  |
| `entity_type` | TEXT | no |  |  |
| `effective_from` | DATE | no |  |  |
| `effective_to` | DATE | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.departments`

Global department master.

- Primary key: `department_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `department_id` | TEXT | no |  |  |
| `department_name` | TEXT | no |  |  |
| `functional_area` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.cost_centers`

Cost centers (entity x department).

- Primary key: `cost_center_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `cost_center_id` | TEXT | no |  |  |
| `cost_center_name` | TEXT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `department_id` | TEXT | no |  |  |
| `manager_employee_id` | BIGINT | yes |  |  |
| `is_active` | BOOLEAN | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.profit_centers`

Profit centers (entity x product line).

- Primary key: `profit_center_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `profit_center_id` | TEXT | no |  |  |
| `profit_center_name` | TEXT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `product_line` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.products`

Product and service catalogue.

- Primary key: `product_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `product_id` | TEXT | no |  |  |
| `product_name` | TEXT | no |  |  |
| `product_line` | TEXT | no |  |  |
| `revenue_type` | TEXT | no |  |  |
| `list_price_eur` | NUMERIC(19,4) | no |  |  |
| `standard_cost_ratio` | NUMERIC(9,4) | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.accounts`

Local (entity) chart of accounts. Posting accounts only; the group hierarchy is in the group CoA.

- Primary key: `account_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `account_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `account_code` | TEXT | no |  |  |
| `account_name` | TEXT | no |  |  |
| `account_type` | TEXT | no |  |  |
| `account_category` | TEXT | no |  |  |
| `parent_account_id` | BIGINT | yes |  |  |
| `reporting_group` | TEXT | yes |  |  |
| `normal_balance` | TEXT | no |  |  |
| `account_status` | TEXT | no |  |  |
| `bank_account_id` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.account_mappings`

Local-to-group account mapping maintained by group reporting.

- Primary key: `mapping_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `mapping_id` | BIGINT | no |  |  |
| `account_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `group_account_code` | TEXT | no |  |  |
| `valid_from` | DATE | no |  |  |
| `valid_to` | DATE | yes |  |  |
| `mapping_version` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.customer_accounts`

ERP receivable accounts referencing the CRM customer master (cross-system key mapping).

- Primary key: `erp_customer_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `erp_customer_id` | BIGINT | no |  |  |
| `crm_customer_id` | BIGINT | yes |  |  |
| `entity_id` | TEXT | no |  |  |
| `intercompany_entity_id` | TEXT | yes |  |  |
| `payment_terms_days` | BIGINT | no |  |  |
| `credit_limit` | NUMERIC(19,4) | yes |  |  |
| `billing_currency` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.vendors`

Supplier master.

- Primary key: `vendor_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `vendor_id` | BIGINT | no |  |  |
| `vendor_number` | TEXT | no |  |  |
| `vendor_name` | TEXT | no |  |  |
| `vendor_category` | TEXT | no |  |  |
| `country` | TEXT | no |  |  |
| `currency` | TEXT | no |  |  |
| `payment_terms_days` | BIGINT | no |  |  |
| `early_payment_discount_pct` | NUMERIC(9,4) | yes |  |  |
| `early_payment_discount_days` | BIGINT | yes |  |  |
| `bank_account_masked` | TEXT | yes | FINANCIAL_ACCOUNT |  |
| `tax_id` | TEXT | yes | PII |  |
| `vendor_status` | TEXT | no |  |  |
| `is_intercompany` | BOOLEAN | no |  |  |
| `intercompany_entity_id` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.bank_accounts`

House bank accounts.

- Primary key: `bank_account_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `bank_account_id` | TEXT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `bank_name` | TEXT | no |  |  |
| `account_number_masked` | TEXT | no | FINANCIAL_ACCOUNT |  |
| `currency` | TEXT | no |  |  |
| `account_purpose` | TEXT | no |  |  |
| `gl_account_id` | BIGINT | no |  |  |
| `opened_date` | DATE | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.accounting_periods`

Accounting periods per entity with current status.

- Primary key: `entity_id, fiscal_period`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `entity_id` | TEXT | no |  |  |
| `fiscal_period` | TEXT | no |  |  |
| `fiscal_year` | BIGINT | no |  |  |
| `period_number` | BIGINT | no |  |  |
| `period_start` | DATE | no |  |  |
| `period_end` | DATE | no |  |  |
| `period_status` | TEXT | no |  |  |
| `status_changed_at` | TIMESTAMPTZ | no |  |  |
| `status_changed_by` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.period_status_changes`

Audit trail of accounting period status transitions.

- Primary key: `change_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `change_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `fiscal_period` | TEXT | no |  |  |
| `from_status` | TEXT | yes |  |  |
| `to_status` | TEXT | no |  |  |
| `changed_at` | TIMESTAMPTZ | no |  |  |
| `changed_by` | TEXT | no |  |  |
| `reason` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.journal_headers`

General ledger journal headers. Posted journals are immutable; corrections are reversals.

- Primary key: `journal_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `journal_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `journal_type` | TEXT | no |  |  |
| `posting_date` | DATE | no |  |  |
| `transaction_date` | DATE | no |  |  |
| `fiscal_period` | TEXT | no |  |  |
| `source_system` | TEXT | no |  |  |
| `source_document_type` | TEXT | yes |  |  |
| `source_document_id` | TEXT | yes |  |  |
| `reference_number` | TEXT | yes |  |  |
| `description` | TEXT | yes |  |  |
| `posting_status` | TEXT | no |  |  |
| `reversal_of_journal_id` | BIGINT | yes |  |  |
| `created_by` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.journal_lines`

Journal lines. debit/credit and functional_currency_amount are in the entity functional currency; transaction_amount and functional_currency_amount are signed debit-positive.

- Primary key: `journal_line_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `journal_line_id` | BIGINT | no |  |  |
| `journal_id` | BIGINT | no |  |  |
| `line_number` | BIGINT | no |  |  |
| `account_id` | BIGINT | no |  |  |
| `debit_amount` | NUMERIC(19,4) | no |  |  |
| `credit_amount` | NUMERIC(19,4) | no |  |  |
| `transaction_currency` | TEXT | no |  |  |
| `transaction_amount` | NUMERIC(19,4) | no |  |  |
| `functional_currency` | TEXT | no |  |  |
| `functional_currency_amount` | NUMERIC(19,4) | no |  |  |
| `exchange_rate` | NUMERIC(24,10) | no |  |  |
| `cost_center_id` | TEXT | yes |  |  |
| `profit_center_id` | TEXT | yes |  |  |
| `department_id` | TEXT | yes |  |  |
| `counterparty_entity_id` | TEXT | yes |  |  |
| `line_description` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.opening_balances`

Opening balances at migration date (also posted as OPENING journals).

- Primary key: `entity_id, account_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `entity_id` | TEXT | no |  |  |
| `account_id` | BIGINT | no |  |  |
| `balance_date` | DATE | no |  |  |
| `functional_currency` | TEXT | no |  |  |
| `balance_amount` | NUMERIC(19,4) | no |  |  |
| `journal_id` | BIGINT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.customer_invoices`

Customer (AR) invoices. outstanding_amount/status are the ERP's current view.

- Primary key: `invoice_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `invoice_id` | BIGINT | no |  |  |
| `invoice_number` | TEXT | no |  |  |
| `erp_customer_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `sales_order_id` | BIGINT | yes |  |  |
| `invoice_date` | DATE | no |  |  |
| `due_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `subtotal` | NUMERIC(19,4) | no |  |  |
| `tax_amount` | NUMERIC(19,4) | no |  |  |
| `invoice_amount` | NUMERIC(19,4) | no |  |  |
| `outstanding_amount` | NUMERIC(19,4) | no |  |  |
| `invoice_status` | TEXT | no |  |  |
| `is_intercompany` | BOOLEAN | no |  |  |
| `counterparty_entity_id` | TEXT | yes |  |  |
| `journal_id` | BIGINT | yes |  |  |
| `is_deleted` | BOOLEAN | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.customer_invoice_lines`

Customer invoice lines.

- Primary key: `invoice_line_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `invoice_line_id` | BIGINT | no |  |  |
| `invoice_id` | BIGINT | no |  |  |
| `line_number` | BIGINT | no |  |  |
| `product_id` | TEXT | no |  |  |
| `quantity` | NUMERIC(18,4) | no |  |  |
| `unit_price` | NUMERIC(19,4) | no |  |  |
| `line_amount` | NUMERIC(19,4) | no |  |  |
| `tax_rate_pct` | NUMERIC(9,4) | no |  |  |
| `tax_amount` | NUMERIC(19,4) | no |  |  |
| `profit_center_id` | TEXT | yes |  |  |
| `revenue_account_id` | BIGINT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.credit_notes`

Customer credit notes.

- Primary key: `credit_note_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `credit_note_id` | BIGINT | no |  |  |
| `credit_note_number` | TEXT | no |  |  |
| `invoice_id` | BIGINT | no |  |  |
| `erp_customer_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `credit_note_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `subtotal` | NUMERIC(19,4) | no |  |  |
| `tax_amount` | NUMERIC(19,4) | no |  |  |
| `credit_amount` | NUMERIC(19,4) | no |  |  |
| `functional_amount` | NUMERIC(19,4) | no |  |  |
| `reason_code` | TEXT | no |  |  |
| `journal_id` | BIGINT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.purchase_requisitions`

Purchase requisitions.

- Primary key: `requisition_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `requisition_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `requested_by_employee_id` | BIGINT | yes |  |  |
| `cost_center_id` | TEXT | no |  |  |
| `requisition_date` | DATE | no |  |  |
| `estimated_amount` | NUMERIC(19,4) | no |  |  |
| `currency` | TEXT | no |  |  |
| `approval_status` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.purchase_orders`

Purchase orders.

- Primary key: `purchase_order_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `purchase_order_id` | BIGINT | no |  |  |
| `po_number` | TEXT | no |  |  |
| `requisition_id` | BIGINT | yes |  |  |
| `vendor_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `order_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `order_amount` | NUMERIC(19,4) | no |  |  |
| `po_status` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.purchase_order_lines`

Purchase order lines.

- Primary key: `po_line_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `po_line_id` | BIGINT | no |  |  |
| `purchase_order_id` | BIGINT | no |  |  |
| `line_number` | BIGINT | no |  |  |
| `product_id` | TEXT | yes |  |  |
| `description` | TEXT | no |  |  |
| `quantity` | NUMERIC(18,4) | no |  |  |
| `unit_price` | NUMERIC(19,4) | no |  |  |
| `line_amount` | NUMERIC(19,4) | no |  |  |
| `cost_center_id` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.goods_receipts`

Goods receipts against PO lines.

- Primary key: `goods_receipt_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `goods_receipt_id` | BIGINT | no |  |  |
| `po_line_id` | BIGINT | no |  |  |
| `purchase_order_id` | BIGINT | no |  |  |
| `receipt_date` | DATE | no |  |  |
| `quantity_received` | NUMERIC(18,4) | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.vendor_invoices`

Supplier (AP) invoices.

- Primary key: `vendor_invoice_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `vendor_invoice_id` | BIGINT | no |  |  |
| `vendor_invoice_number` | TEXT | no |  |  |
| `vendor_id` | BIGINT | no |  |  |
| `purchase_order_id` | BIGINT | yes |  |  |
| `entity_id` | TEXT | no |  |  |
| `invoice_date` | DATE | no |  |  |
| `received_date` | DATE | no |  |  |
| `due_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `subtotal` | NUMERIC(19,4) | no |  |  |
| `tax_amount` | NUMERIC(19,4) | no |  |  |
| `invoice_amount` | NUMERIC(19,4) | no |  |  |
| `approved_amount` | NUMERIC(19,4) | no |  |  |
| `outstanding_amount` | NUMERIC(19,4) | no |  |  |
| `payment_status` | TEXT | no |  |  |
| `approval_status` | TEXT | no |  |  |
| `expense_category` | TEXT | no |  |  |
| `is_intercompany` | BOOLEAN | no |  |  |
| `counterparty_entity_id` | TEXT | yes |  |  |
| `journal_id` | BIGINT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.vendor_invoice_lines`

Supplier invoice lines.

- Primary key: `vendor_invoice_line_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `vendor_invoice_line_id` | BIGINT | no |  |  |
| `vendor_invoice_id` | BIGINT | no |  |  |
| `line_number` | BIGINT | no |  |  |
| `po_line_id` | BIGINT | yes |  |  |
| `description` | TEXT | no |  |  |
| `quantity` | NUMERIC(18,4) | no |  |  |
| `unit_price` | NUMERIC(19,4) | no |  |  |
| `line_amount` | NUMERIC(19,4) | no |  |  |
| `tax_rate_pct` | NUMERIC(9,4) | no |  |  |
| `tax_amount` | NUMERIC(19,4) | no |  |  |
| `expense_account_id` | BIGINT | no |  |  |
| `cost_center_id` | TEXT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.payments`

Cash payments and receipts recorded in the ERP treasury module.

- Primary key: `payment_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `payment_id` | BIGINT | no |  |  |
| `payment_number` | TEXT | no |  |  |
| `payment_date` | DATE | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `payment_direction` | TEXT | no |  |  |
| `payment_type` | TEXT | no |  |  |
| `payment_method` | TEXT | no |  |  |
| `currency` | TEXT | no |  |  |
| `payment_amount` | NUMERIC(19,4) | no |  |  |
| `functional_amount` | NUMERIC(19,4) | no |  |  |
| `bank_charge_amount` | NUMERIC(19,4) | no |  |  |
| `payment_status` | TEXT | no |  |  |
| `bank_account_id` | TEXT | no |  |  |
| `bank_reference` | TEXT | no |  |  |
| `counterparty_type` | TEXT | yes |  |  |
| `counterparty_id` | TEXT | yes |  |  |
| `journal_id` | BIGINT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.payment_allocations`

Allocation of payments to invoices/credit notes (many-to-many settlement).

- Primary key: `allocation_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `allocation_id` | BIGINT | no |  |  |
| `payment_id` | BIGINT | no |  |  |
| `document_type` | TEXT | no |  |  |
| `document_id` | BIGINT | no |  |  |
| `allocation_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `allocated_amount` | NUMERIC(19,4) | no |  |  |
| `discount_amount` | NUMERIC(19,4) | no |  |  |
| `functional_amount_relieved` | NUMERIC(19,4) | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.fixed_assets`

Fixed asset register.

- Primary key: `asset_id`  
- Delivery: `postgres` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `asset_id` | BIGINT | no |  |  |
| `asset_number` | TEXT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `asset_class` | TEXT | no |  |  |
| `description` | TEXT | no |  |  |
| `acquisition_date` | DATE | no |  |  |
| `in_service_date` | DATE | no |  |  |
| `acquisition_cost` | NUMERIC(19,4) | no |  |  |
| `currency` | TEXT | no |  |  |
| `useful_life_months` | BIGINT | no |  |  |
| `salvage_value` | NUMERIC(19,4) | no |  |  |
| `depreciation_method` | TEXT | no |  |  |
| `cost_center_id` | TEXT | yes |  |  |
| `vendor_invoice_id` | BIGINT | yes |  |  |
| `asset_status` | TEXT | no |  |  |
| `disposal_date` | DATE | yes |  |  |
| `disposal_proceeds` | NUMERIC(19,4) | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.depreciation_schedule`

Posted monthly depreciation per asset.

- Primary key: `asset_id, fiscal_period`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `asset_id` | BIGINT | no |  |  |
| `fiscal_period` | TEXT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `depreciation_amount` | NUMERIC(19,4) | no |  |  |
| `accumulated_depreciation` | NUMERIC(19,4) | no |  |  |
| `net_book_value` | NUMERIC(19,4) | no |  |  |
| `journal_id` | BIGINT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.tax_transactions`

Indirect tax (VAT/GST) register.

- Primary key: `tax_transaction_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `tax_transaction_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `tax_date` | DATE | no |  |  |
| `tax_type` | TEXT | no |  |  |
| `tax_direction` | TEXT | no |  |  |
| `source_document_type` | TEXT | no |  |  |
| `source_document_id` | BIGINT | no |  |  |
| `taxable_amount` | NUMERIC(19,4) | no |  |  |
| `tax_rate_pct` | NUMERIC(9,4) | no |  |  |
| `tax_amount` | NUMERIC(19,4) | no |  |  |
| `currency` | TEXT | no |  |  |
| `functional_tax_amount` | NUMERIC(19,4) | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.intercompany_transactions`

Intercompany agreement register linking both sides of each IC charge.

- Primary key: `ic_transaction_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `ic_transaction_id` | BIGINT | no |  |  |
| `ic_reference` | TEXT | no |  |  |
| `seller_entity_id` | TEXT | no |  |  |
| `buyer_entity_id` | TEXT | no |  |  |
| `transaction_date` | DATE | no |  |  |
| `service_type` | TEXT | no |  |  |
| `currency` | TEXT | no |  |  |
| `amount` | NUMERIC(19,4) | no |  |  |
| `seller_invoice_id` | BIGINT | yes |  |  |
| `buyer_vendor_invoice_id` | BIGINT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `erp.loans`

External borrowings.

- Primary key: `loan_id`  
- Delivery: `postgres` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `loan_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `lender_name` | TEXT | no |  |  |
| `currency` | TEXT | no |  |  |
| `principal_amount` | NUMERIC(19,4) | no |  |  |
| `annual_interest_rate_pct` | NUMERIC(9,4) | no |  |  |
| `drawdown_date` | DATE | no |  |  |
| `maturity_date` | DATE | no |  |  |
| `is_long_term` | BOOLEAN | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

## `fx`

### `fx.exchange_rates`

Published exchange rates: target units per one source unit. Corrections are re-publications.

- Primary key: `rate_date, source_currency, target_currency, rate_type, publication_timestamp`  
- Delivery: `csv` · append-only · watermark `publication_timestamp`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `rate_date` | DATE | no |  |  |
| `source_currency` | TEXT | no |  |  |
| `target_currency` | TEXT | no |  |  |
| `exchange_rate` | NUMERIC(24,10) | no |  |  |
| `rate_type` | TEXT | no |  |  |
| `provider` | TEXT | no |  |  |
| `publication_timestamp` | TIMESTAMPTZ | no |  |  |

## `payroll`

### `payroll.employees`

Employee master (current state).

- Primary key: `employee_id`  
- Delivery: `csv` · mutable (versions keyed by `updated_at`) · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `employee_id` | BIGINT | no |  |  |
| `employee_number` | TEXT | no |  |  |
| `first_name` | TEXT | no | PII |  |
| `last_name` | TEXT | no | PII |  |
| `entity_id` | TEXT | no |  |  |
| `department_id` | TEXT | no |  |  |
| `cost_center_id` | TEXT | no |  |  |
| `job_title` | TEXT | no |  |  |
| `grade` | TEXT | no |  |  |
| `annual_salary` | NUMERIC(19,4) | no | PAYROLL |  |
| `salary_currency` | TEXT | no |  |  |
| `hire_date` | DATE | no |  |  |
| `termination_date` | DATE | yes |  |  |
| `employment_status` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `payroll.employee_job_history`

Effective-dated job and compensation history.

- Primary key: `employee_id, effective_from`  
- Delivery: `csv` · append-only · watermark `updated_at`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `employee_id` | BIGINT | no |  |  |
| `effective_from` | DATE | no |  |  |
| `effective_to` | DATE | yes |  |  |
| `entity_id` | TEXT | no |  |  |
| `department_id` | TEXT | no |  |  |
| `cost_center_id` | TEXT | no |  |  |
| `job_title` | TEXT | no |  |  |
| `grade` | TEXT | no |  |  |
| `annual_salary` | NUMERIC(19,4) | no | PAYROLL |  |
| `change_reason` | TEXT | no |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `payroll.payroll_transactions`

Payroll results per employee and pay period.

- Primary key: `payroll_line_id`  
- Delivery: `csv` · append-only · watermark `pay_date`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `payroll_line_id` | BIGINT | no |  |  |
| `payroll_run_id` | TEXT | no |  |  |
| `employee_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `cost_center_id` | TEXT | no |  |  |
| `department_id` | TEXT | no |  |  |
| `pay_period` | TEXT | no |  |  |
| `pay_date` | DATE | no |  |  |
| `currency` | TEXT | no |  |  |
| `gross_salary` | NUMERIC(19,4) | no | PAYROLL |  |
| `employee_tax_withheld` | NUMERIC(19,4) | no |  |  |
| `employer_contributions` | NUMERIC(19,4) | no |  |  |
| `expense_reimbursement` | NUMERIC(19,4) | no |  |  |
| `net_pay` | NUMERIC(19,4) | no | PAYROLL |  |
| `journal_id` | BIGINT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |

### `payroll.expense_claims`

Employee expense claims reimbursed through payroll.

- Primary key: `expense_claim_id`  
- Delivery: `csv` · append-only · watermark `claim_date`  
- Owner: Finance Data Engineering

| Column | Type | Null | Sensitive | Description |
|---|---|---|---|---|
| `expense_claim_id` | BIGINT | no |  |  |
| `employee_id` | BIGINT | no |  |  |
| `entity_id` | TEXT | no |  |  |
| `cost_center_id` | TEXT | no |  |  |
| `claim_date` | DATE | no |  |  |
| `expense_category` | TEXT | no |  |  |
| `currency` | TEXT | no |  |  |
| `claim_amount` | NUMERIC(19,4) | no |  |  |
| `claim_status` | TEXT | no |  |  |
| `reimbursed_in_period` | TEXT | yes |  |  |
| `journal_id` | BIGINT | yes |  |  |
| `created_at` | TIMESTAMPTZ | no |  |  |
| `updated_at` | TIMESTAMPTZ | no |  |  |
