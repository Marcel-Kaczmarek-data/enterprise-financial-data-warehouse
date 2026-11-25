# Power BI semantic model (specification)

**Status: specification only, not built and not tested.** This repository contains no `.pbix` file on purpose.
A PBIX made without the real model and data would be a fake. This folder describes the model a BI developer
would build on the Snowflake `FINANCE_MARTS` / `FINANCE_CORE` schemas, and gives the DAX measures, which
are not validated in Power BI. The Streamlit dashboard (`dashboards/streamlit`) is the implemented and
tested reporting layer.

## Connection

| Setting | Value |
|---|---|
| Source | Snowflake connector, warehouse `FINANCE_BI_WH`, role `BI_SERVICE` (read-only, row-access policy by entity) |
| Mode | Import for marts (refreshed after the publication gate, asset `finance_marts_published`), DirectQuery not needed |
| Incremental refresh | `fact_general_ledger` on `posting_date`, 5 years stored, last 2 months refreshed (late postings / reopened periods) |

## Star schema

| Table | Grain | Relationships |
|---|---|---|
| `fact_general_ledger` | journal line | `dim_date[date_key]` (posting), `dim_legal_entity`, `dim_account`, `dim_cost_center` (all single-direction, many-to-one) |
| `fact_monthly_account_balances` | entity × account × period | `dim_fiscal_period`, `dim_legal_entity`, `dim_account` |
| `mart_profit_and_loss` | scope × entity × period × statement line | `dim_fiscal_period`, `dim_legal_entity` |
| `mart_balance_sheet` | scope × entity × period × statement line | as above (semi-additive: never summed across periods) |
| `fact_receivables_snapshot` / `fact_payables_snapshot` | open item × snapshot date | `dim_date`, `dim_customer` / `dim_vendor` |
| `mart_budget_vs_actual` | entity × cost center × account × period × version | `dim_fiscal_period`, `dim_cost_center` |
| `dim_fiscal_period` | month | marked as the date table for time intelligence on periods |

## Report pages (same scope as the Streamlit pages)

Executive overview · P&L · Balance sheet · Cash flow & treasury · Budget vs actual · AR · AP ·
Revenue & profitability · Cost centers · Consolidation · Reconciliation · Close · Data quality.

## Measures

See [`measures.dax`](measures.dax). Rules followed:

* Balance-sheet measures take the **last period in context** (`LASTNONBLANK`), and never sum across months.
* Amounts come from the warehouse already translated to EUR. Power BI does no currency conversion.
* Ratios use `DIVIDE` (safe division), the same as the `safe_divide` macro in dbt.
