"""Source data contracts: the single definition of every source-system table.

The registry drives
* the generator's typed Parquet output,
* the PostgreSQL DDL of the simulated ERP,
* schema validation during ingestion,
* the generated data-contract documentation (docs/data-contracts.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pyarrow as pa

LOGICAL_TYPES: dict[str, tuple[pa.DataType, str]] = {
    # logical -> (arrow type, postgres type)
    "int": (pa.int64(), "BIGINT"),
    "str": (pa.string(), "TEXT"),
    "date": (pa.date32(), "DATE"),
    "ts": (pa.timestamp("us", tz="UTC"), "TIMESTAMPTZ"),
    "money": (pa.decimal128(19, 4), "NUMERIC(19,4)"),
    "rate": (pa.decimal128(24, 10), "NUMERIC(24,10)"),
    "qty": (pa.decimal128(18, 4), "NUMERIC(18,4)"),
    "pct": (pa.decimal128(9, 4), "NUMERIC(9,4)"),
    "bool": (pa.bool_(), "BOOLEAN"),
}


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    nullable: bool = True
    description: str = ""
    sensitive: str | None = None  # PII | FINANCIAL_ACCOUNT | PAYROLL


@dataclass(frozen=True)
class TableContract:
    system: str
    name: str
    primary_key: tuple[str, ...]
    columns: tuple[Column, ...]
    description: str
    mutable: bool = False  # mutable records are emitted as versions keyed by updated_at
    watermark: tuple[str, ...] = ("updated_at",)
    delivery: str = "postgres"  # postgres | api | csv | json | excel
    owner: str = "Finance Data Engineering"
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def fqn(self) -> str:
        return f"{self.system}.{self.name}"

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    def arrow_schema(self) -> pa.Schema:
        return pa.schema([pa.field(c.name, LOGICAL_TYPES[c.type][0], nullable=c.nullable) for c in self.columns])

    def postgres_ddl(self, schema: str) -> str:
        cols = [f'    "{c.name}" {LOGICAL_TYPES[c.type][1]}{"" if c.nullable else " NOT NULL"}' for c in self.columns]
        pk = ", ".join(f'"{k}"' for k in self.primary_key)
        cols.append(f"    PRIMARY KEY ({pk})")
        body = ",\n".join(cols)
        return f'CREATE TABLE IF NOT EXISTS {schema}."{self.name}" (\n{body}\n);'


def C(name: str, type_: str, nullable: bool = True, description: str = "", sensitive: str | None = None) -> Column:
    return Column(name, type_, nullable, description, sensitive)


AUDIT_COLS = (C("created_at", "ts", False), C("updated_at", "ts", False))

_T: list[TableContract] = []


def _reg(t: TableContract) -> TableContract:
    _T.append(t)
    return t


# --------------------------------------------------------------------------------------------- ERP
_reg(
    TableContract(
        "erp",
        "legal_entities",
        ("entity_id",),
        (
            C("entity_id", "str", False),
            C("parent_entity_id", "str"),
            C("entity_name", "str", False),
            C("country", "str", False),
            C("functional_currency", "str", False),
            C("reporting_currency", "str", False),
            C("fiscal_calendar", "str", False),
            C("ownership_percentage", "pct", False),
            C("entity_type", "str", False),
            C("effective_from", "date", False),
            C("effective_to", "date"),
            *AUDIT_COLS,
        ),
        "Legal entity master and ownership hierarchy.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "departments",
        ("department_id",),
        (
            C("department_id", "str", False),
            C("department_name", "str", False),
            C("functional_area", "str", False),
            *AUDIT_COLS,
        ),
        "Global department master.",
    )
)

_reg(
    TableContract(
        "erp",
        "cost_centers",
        ("cost_center_id",),
        (
            C("cost_center_id", "str", False),
            C("cost_center_name", "str", False),
            C("entity_id", "str", False),
            C("department_id", "str", False),
            C("manager_employee_id", "int"),
            C("is_active", "bool", False),
            *AUDIT_COLS,
        ),
        "Cost centers (entity x department).",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "profit_centers",
        ("profit_center_id",),
        (
            C("profit_center_id", "str", False),
            C("profit_center_name", "str", False),
            C("entity_id", "str", False),
            C("product_line", "str", False),
            *AUDIT_COLS,
        ),
        "Profit centers (entity x product line).",
    )
)

_reg(
    TableContract(
        "erp",
        "products",
        ("product_id",),
        (
            C("product_id", "str", False),
            C("product_name", "str", False),
            C("product_line", "str", False),
            C("revenue_type", "str", False),
            C("list_price_eur", "money", False),
            C("standard_cost_ratio", "pct", False),
            *AUDIT_COLS,
        ),
        "Product and service catalogue.",
    )
)

_reg(
    TableContract(
        "erp",
        "accounts",
        ("account_id",),
        (
            C("account_id", "int", False),
            C("entity_id", "str", False),
            C("account_code", "str", False),
            C("account_name", "str", False),
            C("account_type", "str", False),
            C("account_category", "str", False),
            C("parent_account_id", "int"),
            C("reporting_group", "str"),
            C("normal_balance", "str", False),
            C("account_status", "str", False),
            C("bank_account_id", "str"),
            *AUDIT_COLS,
        ),
        "Local (entity) chart of accounts. Posting accounts only; the group hierarchy is in the group CoA.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "account_mappings",
        ("mapping_id",),
        (
            C("mapping_id", "int", False),
            C("account_id", "int", False),
            C("entity_id", "str", False),
            C("group_account_code", "str", False),
            C("valid_from", "date", False),
            C("valid_to", "date"),
            C("mapping_version", "str", False),
            *AUDIT_COLS,
        ),
        "Local-to-group account mapping maintained by group reporting.",
    )
)

_reg(
    TableContract(
        "erp",
        "customer_accounts",
        ("erp_customer_id",),
        (
            C("erp_customer_id", "int", False),
            C("crm_customer_id", "int"),
            C("entity_id", "str", False),
            C("intercompany_entity_id", "str"),
            C("payment_terms_days", "int", False),
            C("credit_limit", "money"),
            C("billing_currency", "str", False),
            *AUDIT_COLS,
        ),
        "ERP receivable accounts referencing the CRM customer master (cross-system key mapping).",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "vendors",
        ("vendor_id",),
        (
            C("vendor_id", "int", False),
            C("vendor_number", "str", False),
            C("vendor_name", "str", False),
            C("vendor_category", "str", False),
            C("country", "str", False),
            C("currency", "str", False),
            C("payment_terms_days", "int", False),
            C("early_payment_discount_pct", "pct"),
            C("early_payment_discount_days", "int"),
            C("bank_account_masked", "str", sensitive="FINANCIAL_ACCOUNT"),
            C("tax_id", "str", sensitive="PII"),
            C("vendor_status", "str", False),
            C("is_intercompany", "bool", False),
            C("intercompany_entity_id", "str"),
            *AUDIT_COLS,
        ),
        "Supplier master.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "bank_accounts",
        ("bank_account_id",),
        (
            C("bank_account_id", "str", False),
            C("entity_id", "str", False),
            C("bank_name", "str", False),
            C("account_number_masked", "str", False, sensitive="FINANCIAL_ACCOUNT"),
            C("currency", "str", False),
            C("account_purpose", "str", False),
            C("gl_account_id", "int", False),
            C("opened_date", "date", False),
            *AUDIT_COLS,
        ),
        "House bank accounts.",
    )
)

_reg(
    TableContract(
        "erp",
        "accounting_periods",
        ("entity_id", "fiscal_period"),
        (
            C("entity_id", "str", False),
            C("fiscal_period", "str", False),
            C("fiscal_year", "int", False),
            C("period_number", "int", False),
            C("period_start", "date", False),
            C("period_end", "date", False),
            C("period_status", "str", False),
            C("status_changed_at", "ts", False),
            C("status_changed_by", "str"),
            *AUDIT_COLS,
        ),
        "Accounting periods per entity with current status.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "period_status_changes",
        ("change_id",),
        (
            C("change_id", "int", False),
            C("entity_id", "str", False),
            C("fiscal_period", "str", False),
            C("from_status", "str"),
            C("to_status", "str", False),
            C("changed_at", "ts", False),
            C("changed_by", "str", False),
            C("reason", "str"),
            *AUDIT_COLS,
        ),
        "Audit trail of accounting period status transitions.",
    )
)

_reg(
    TableContract(
        "erp",
        "journal_headers",
        ("journal_id",),
        (
            C("journal_id", "int", False),
            C("entity_id", "str", False),
            C("journal_type", "str", False),
            C("posting_date", "date", False),
            C("transaction_date", "date", False),
            C("fiscal_period", "str", False),
            C("source_system", "str", False),
            C("source_document_type", "str"),
            C("source_document_id", "str"),
            C("reference_number", "str"),
            C("description", "str"),
            C("posting_status", "str", False),
            C("reversal_of_journal_id", "int"),
            C("created_by", "str", False),
            *AUDIT_COLS,
        ),
        "General ledger journal headers. Posted journals are immutable; corrections are reversals.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "journal_lines",
        ("journal_line_id",),
        (
            C("journal_line_id", "int", False),
            C("journal_id", "int", False),
            C("line_number", "int", False),
            C("account_id", "int", False),
            C("debit_amount", "money", False),
            C("credit_amount", "money", False),
            C("transaction_currency", "str", False),
            C("transaction_amount", "money", False),
            C("functional_currency", "str", False),
            C("functional_currency_amount", "money", False),
            C("exchange_rate", "rate", False),
            C("cost_center_id", "str"),
            C("profit_center_id", "str"),
            C("department_id", "str"),
            C("counterparty_entity_id", "str"),
            C("line_description", "str"),
            *AUDIT_COLS,
        ),
        "Journal lines. debit/credit and functional_currency_amount are in the entity functional "
        "currency; transaction_amount and functional_currency_amount are signed debit-positive.",
    )
)

_reg(
    TableContract(
        "erp",
        "opening_balances",
        ("entity_id", "account_id"),
        (
            C("entity_id", "str", False),
            C("account_id", "int", False),
            C("balance_date", "date", False),
            C("functional_currency", "str", False),
            C("balance_amount", "money", False),
            C("journal_id", "int", False),
            *AUDIT_COLS,
        ),
        "Opening balances at migration date (also posted as OPENING journals).",
    )
)

_reg(
    TableContract(
        "erp",
        "customer_invoices",
        ("invoice_id",),
        (
            C("invoice_id", "int", False),
            C("invoice_number", "str", False),
            C("erp_customer_id", "int", False),
            C("entity_id", "str", False),
            C("sales_order_id", "int"),
            C("invoice_date", "date", False),
            C("due_date", "date", False),
            C("currency", "str", False),
            C("subtotal", "money", False),
            C("tax_amount", "money", False),
            C("invoice_amount", "money", False),
            C("outstanding_amount", "money", False),
            C("invoice_status", "str", False),
            C("is_intercompany", "bool", False),
            C("counterparty_entity_id", "str"),
            C("journal_id", "int"),
            C("is_deleted", "bool", False),
            *AUDIT_COLS,
        ),
        "Customer (AR) invoices. outstanding_amount/status are the ERP's current view.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "customer_invoice_lines",
        ("invoice_line_id",),
        (
            C("invoice_line_id", "int", False),
            C("invoice_id", "int", False),
            C("line_number", "int", False),
            C("product_id", "str", False),
            C("quantity", "qty", False),
            C("unit_price", "money", False),
            C("line_amount", "money", False),
            C("tax_rate_pct", "pct", False),
            C("tax_amount", "money", False),
            C("profit_center_id", "str"),
            C("revenue_account_id", "int", False),
            *AUDIT_COLS,
        ),
        "Customer invoice lines.",
    )
)

_reg(
    TableContract(
        "erp",
        "credit_notes",
        ("credit_note_id",),
        (
            C("credit_note_id", "int", False),
            C("credit_note_number", "str", False),
            C("invoice_id", "int", False),
            C("erp_customer_id", "int", False),
            C("entity_id", "str", False),
            C("credit_note_date", "date", False),
            C("currency", "str", False),
            C("subtotal", "money", False),
            C("tax_amount", "money", False),
            C("credit_amount", "money", False),
            C("functional_amount", "money", False),
            C("reason_code", "str", False),
            C("journal_id", "int"),
            *AUDIT_COLS,
        ),
        "Customer credit notes.",
    )
)

_reg(
    TableContract(
        "erp",
        "purchase_requisitions",
        ("requisition_id",),
        (
            C("requisition_id", "int", False),
            C("entity_id", "str", False),
            C("requested_by_employee_id", "int"),
            C("cost_center_id", "str", False),
            C("requisition_date", "date", False),
            C("estimated_amount", "money", False),
            C("currency", "str", False),
            C("approval_status", "str", False),
            *AUDIT_COLS,
        ),
        "Purchase requisitions.",
    )
)

_reg(
    TableContract(
        "erp",
        "purchase_orders",
        ("purchase_order_id",),
        (
            C("purchase_order_id", "int", False),
            C("po_number", "str", False),
            C("requisition_id", "int"),
            C("vendor_id", "int", False),
            C("entity_id", "str", False),
            C("order_date", "date", False),
            C("currency", "str", False),
            C("order_amount", "money", False),
            C("po_status", "str", False),
            *AUDIT_COLS,
        ),
        "Purchase orders.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "purchase_order_lines",
        ("po_line_id",),
        (
            C("po_line_id", "int", False),
            C("purchase_order_id", "int", False),
            C("line_number", "int", False),
            C("product_id", "str"),
            C("description", "str", False),
            C("quantity", "qty", False),
            C("unit_price", "money", False),
            C("line_amount", "money", False),
            C("cost_center_id", "str"),
            *AUDIT_COLS,
        ),
        "Purchase order lines.",
    )
)

_reg(
    TableContract(
        "erp",
        "goods_receipts",
        ("goods_receipt_id",),
        (
            C("goods_receipt_id", "int", False),
            C("po_line_id", "int", False),
            C("purchase_order_id", "int", False),
            C("receipt_date", "date", False),
            C("quantity_received", "qty", False),
            *AUDIT_COLS,
        ),
        "Goods receipts against PO lines.",
    )
)

_reg(
    TableContract(
        "erp",
        "vendor_invoices",
        ("vendor_invoice_id",),
        (
            C("vendor_invoice_id", "int", False),
            C("vendor_invoice_number", "str", False),
            C("vendor_id", "int", False),
            C("purchase_order_id", "int"),
            C("entity_id", "str", False),
            C("invoice_date", "date", False),
            C("received_date", "date", False),
            C("due_date", "date", False),
            C("currency", "str", False),
            C("subtotal", "money", False),
            C("tax_amount", "money", False),
            C("invoice_amount", "money", False),
            C("approved_amount", "money", False),
            C("outstanding_amount", "money", False),
            C("payment_status", "str", False),
            C("approval_status", "str", False),
            C("expense_category", "str", False),
            C("is_intercompany", "bool", False),
            C("counterparty_entity_id", "str"),
            C("journal_id", "int"),
            *AUDIT_COLS,
        ),
        "Supplier (AP) invoices.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "vendor_invoice_lines",
        ("vendor_invoice_line_id",),
        (
            C("vendor_invoice_line_id", "int", False),
            C("vendor_invoice_id", "int", False),
            C("line_number", "int", False),
            C("po_line_id", "int"),
            C("description", "str", False),
            C("quantity", "qty", False),
            C("unit_price", "money", False),
            C("line_amount", "money", False),
            C("tax_rate_pct", "pct", False),
            C("tax_amount", "money", False),
            C("expense_account_id", "int", False),
            C("cost_center_id", "str"),
            *AUDIT_COLS,
        ),
        "Supplier invoice lines.",
    )
)

_reg(
    TableContract(
        "erp",
        "payments",
        ("payment_id",),
        (
            C("payment_id", "int", False),
            C("payment_number", "str", False),
            C("payment_date", "date", False),
            C("entity_id", "str", False),
            C("payment_direction", "str", False),
            C("payment_type", "str", False),
            C("payment_method", "str", False),
            C("currency", "str", False),
            C("payment_amount", "money", False),
            C("functional_amount", "money", False),
            C("bank_charge_amount", "money", False),
            C("payment_status", "str", False),
            C("bank_account_id", "str", False),
            C("bank_reference", "str", False),
            C("counterparty_type", "str"),
            C("counterparty_id", "str"),
            C("journal_id", "int"),
            *AUDIT_COLS,
        ),
        "Cash payments and receipts recorded in the ERP treasury module.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "payment_allocations",
        ("allocation_id",),
        (
            C("allocation_id", "int", False),
            C("payment_id", "int", False),
            C("document_type", "str", False),
            C("document_id", "int", False),
            C("allocation_date", "date", False),
            C("currency", "str", False),
            C("allocated_amount", "money", False),
            C("discount_amount", "money", False),
            C("functional_amount_relieved", "money", False),
            *AUDIT_COLS,
        ),
        "Allocation of payments to invoices/credit notes (many-to-many settlement).",
    )
)

_reg(
    TableContract(
        "erp",
        "fixed_assets",
        ("asset_id",),
        (
            C("asset_id", "int", False),
            C("asset_number", "str", False),
            C("entity_id", "str", False),
            C("asset_class", "str", False),
            C("description", "str", False),
            C("acquisition_date", "date", False),
            C("in_service_date", "date", False),
            C("acquisition_cost", "money", False),
            C("currency", "str", False),
            C("useful_life_months", "int", False),
            C("salvage_value", "money", False),
            C("depreciation_method", "str", False),
            C("cost_center_id", "str"),
            C("vendor_invoice_id", "int"),
            C("asset_status", "str", False),
            C("disposal_date", "date"),
            C("disposal_proceeds", "money"),
            *AUDIT_COLS,
        ),
        "Fixed asset register.",
        mutable=True,
    )
)

_reg(
    TableContract(
        "erp",
        "depreciation_schedule",
        ("asset_id", "fiscal_period"),
        (
            C("asset_id", "int", False),
            C("fiscal_period", "str", False),
            C("entity_id", "str", False),
            C("depreciation_amount", "money", False),
            C("accumulated_depreciation", "money", False),
            C("net_book_value", "money", False),
            C("journal_id", "int"),
            *AUDIT_COLS,
        ),
        "Posted monthly depreciation per asset.",
    )
)

_reg(
    TableContract(
        "erp",
        "tax_transactions",
        ("tax_transaction_id",),
        (
            C("tax_transaction_id", "int", False),
            C("entity_id", "str", False),
            C("tax_date", "date", False),
            C("tax_type", "str", False),
            C("tax_direction", "str", False),
            C("source_document_type", "str", False),
            C("source_document_id", "int", False),
            C("taxable_amount", "money", False),
            C("tax_rate_pct", "pct", False),
            C("tax_amount", "money", False),
            C("currency", "str", False),
            C("functional_tax_amount", "money", False),
            *AUDIT_COLS,
        ),
        "Indirect tax (VAT/GST) register.",
    )
)

_reg(
    TableContract(
        "erp",
        "intercompany_transactions",
        ("ic_transaction_id",),
        (
            C("ic_transaction_id", "int", False),
            C("ic_reference", "str", False),
            C("seller_entity_id", "str", False),
            C("buyer_entity_id", "str", False),
            C("transaction_date", "date", False),
            C("service_type", "str", False),
            C("currency", "str", False),
            C("amount", "money", False),
            C("seller_invoice_id", "int"),
            C("buyer_vendor_invoice_id", "int"),
            *AUDIT_COLS,
        ),
        "Intercompany agreement register linking both sides of each IC charge.",
    )
)

_reg(
    TableContract(
        "erp",
        "loans",
        ("loan_id",),
        (
            C("loan_id", "int", False),
            C("entity_id", "str", False),
            C("lender_name", "str", False),
            C("currency", "str", False),
            C("principal_amount", "money", False),
            C("annual_interest_rate_pct", "pct", False),
            C("drawdown_date", "date", False),
            C("maturity_date", "date", False),
            C("is_long_term", "bool", False),
            *AUDIT_COLS,
        ),
        "External borrowings.",
    )
)

# --------------------------------------------------------------------------------------------- CRM
_reg(
    TableContract(
        "crm",
        "customers",
        ("customer_id",),
        (
            C("customer_id", "int", False),
            C("customer_number", "str", False),
            C("customer_name", "str", False),
            C("segment", "str", False),
            C("industry", "str", False),
            C("country", "str", False),
            C("home_entity_id", "str", False),
            C("contact_email", "str", sensitive="PII"),
            C("tax_id", "str", sensitive="PII"),
            C("customer_status", "str", False),
            *AUDIT_COLS,
        ),
        "CRM customer master (current state).",
        mutable=True,
        delivery="api",
    )
)

_reg(
    TableContract(
        "crm",
        "customer_history",
        ("customer_id", "valid_from"),
        (
            C("customer_id", "int", False),
            C("valid_from", "ts", False),
            C("segment", "str", False),
            C("industry", "str", False),
            C("country", "str", False),
            C("customer_status", "str", False),
            C("change_reason", "str"),
            *AUDIT_COLS,
        ),
        "CRM field-history audit log for customers.",
        delivery="api",
    )
)

_reg(
    TableContract(
        "crm",
        "opportunities",
        ("opportunity_id",),
        (
            C("opportunity_id", "int", False),
            C("customer_id", "int", False),
            C("entity_id", "str", False),
            C("opportunity_name", "str", False),
            C("stage", "str", False),
            C("amount", "money", False),
            C("currency", "str", False),
            C("probability_pct", "pct", False),
            C("expected_close_date", "date", False),
            C("closed_date", "date"),
            C("is_won", "bool"),
            *AUDIT_COLS,
        ),
        "Sales pipeline.",
        mutable=True,
        delivery="api",
    )
)

_reg(
    TableContract(
        "crm",
        "sales_orders",
        ("sales_order_id",),
        (
            C("sales_order_id", "int", False),
            C("order_number", "str", False),
            C("customer_id", "int", False),
            C("opportunity_id", "int"),
            C("entity_id", "str", False),
            C("order_date", "date", False),
            C("delivery_date", "date"),
            C("currency", "str", False),
            C("order_amount", "money", False),
            C("order_status", "str", False),
            *AUDIT_COLS,
        ),
        "Sales orders.",
        mutable=True,
        delivery="api",
    )
)

_reg(
    TableContract(
        "crm",
        "revenue_forecasts",
        ("forecast_id",),
        (
            C("forecast_id", "int", False),
            C("entity_id", "str", False),
            C("forecast_month", "str", False),
            C("snapshot_date", "date", False),
            C("currency", "str", False),
            C("pipeline_amount", "money", False),
            C("weighted_amount", "money", False),
            *AUDIT_COLS,
        ),
        "Monthly weighted pipeline snapshots.",
        delivery="api",
    )
)

# ----------------------------------------------------------------------------------------- Banking
_reg(
    TableContract(
        "banking",
        "bank_transactions",
        ("bank_transaction_id",),
        (
            C("bank_transaction_id", "str", False),
            C("bank_account_id", "str", False),
            C("transaction_date", "date", False),
            C("value_date", "date", False),
            C("transaction_type", "str", False),
            C("currency", "str", False),
            C("amount", "money", False),
            C("bank_reference", "str"),
            C("description", "str"),
            C("counterparty_name", "str"),
            C("reconciliation_status", "str", False),
            C("statement_id", "str", False),
            *AUDIT_COLS,
        ),
        "Bank statement lines (signed: + inflow, - outflow).",
        delivery="csv",
        watermark=("value_date",),
    )
)

_reg(
    TableContract(
        "banking",
        "account_balances",
        ("bank_account_id", "balance_date"),
        (
            C("bank_account_id", "str", False),
            C("balance_date", "date", False),
            C("currency", "str", False),
            C("opening_balance", "money", False),
            C("closing_balance", "money", False),
            C("statement_id", "str", False),
            *AUDIT_COLS,
        ),
        "End-of-day balances reported by the bank.",
        delivery="json",
        watermark=("balance_date",),
    )
)

# ----------------------------------------------------------------------------------------- Payroll
_reg(
    TableContract(
        "payroll",
        "employees",
        ("employee_id",),
        (
            C("employee_id", "int", False),
            C("employee_number", "str", False),
            C("first_name", "str", False, sensitive="PII"),
            C("last_name", "str", False, sensitive="PII"),
            C("entity_id", "str", False),
            C("department_id", "str", False),
            C("cost_center_id", "str", False),
            C("job_title", "str", False),
            C("grade", "str", False),
            C("annual_salary", "money", False, sensitive="PAYROLL"),
            C("salary_currency", "str", False),
            C("hire_date", "date", False),
            C("termination_date", "date"),
            C("employment_status", "str", False),
            *AUDIT_COLS,
        ),
        "Employee master (current state).",
        mutable=True,
        delivery="csv",
    )
)

_reg(
    TableContract(
        "payroll",
        "employee_job_history",
        ("employee_id", "effective_from"),
        (
            C("employee_id", "int", False),
            C("effective_from", "date", False),
            C("effective_to", "date"),
            C("entity_id", "str", False),
            C("department_id", "str", False),
            C("cost_center_id", "str", False),
            C("job_title", "str", False),
            C("grade", "str", False),
            C("annual_salary", "money", False, sensitive="PAYROLL"),
            C("change_reason", "str", False),
            *AUDIT_COLS,
        ),
        "Effective-dated job and compensation history.",
        delivery="csv",
    )
)

_reg(
    TableContract(
        "payroll",
        "payroll_transactions",
        ("payroll_line_id",),
        (
            C("payroll_line_id", "int", False),
            C("payroll_run_id", "str", False),
            C("employee_id", "int", False),
            C("entity_id", "str", False),
            C("cost_center_id", "str", False),
            C("department_id", "str", False),
            C("pay_period", "str", False),
            C("pay_date", "date", False),
            C("currency", "str", False),
            C("gross_salary", "money", False, sensitive="PAYROLL"),
            C("employee_tax_withheld", "money", False),
            C("employer_contributions", "money", False),
            C("expense_reimbursement", "money", False),
            C("net_pay", "money", False, sensitive="PAYROLL"),
            C("journal_id", "int"),
            *AUDIT_COLS,
        ),
        "Payroll results per employee and pay period.",
        delivery="csv",
        watermark=("pay_date",),
    )
)

_reg(
    TableContract(
        "payroll",
        "expense_claims",
        ("expense_claim_id",),
        (
            C("expense_claim_id", "int", False),
            C("employee_id", "int", False),
            C("entity_id", "str", False),
            C("cost_center_id", "str", False),
            C("claim_date", "date", False),
            C("expense_category", "str", False),
            C("currency", "str", False),
            C("claim_amount", "money", False),
            C("claim_status", "str", False),
            C("reimbursed_in_period", "str"),
            C("journal_id", "int"),
            *AUDIT_COLS,
        ),
        "Employee expense claims reimbursed through payroll.",
        delivery="csv",
        watermark=("claim_date",),
    )
)

# --------------------------------------------------------------------------------------- Budgeting
_reg(
    TableContract(
        "budgeting",
        "budget_plans",
        ("budget_id",),
        (
            C("budget_id", "str", False),
            C("entity_id", "str", False),
            C("fiscal_year", "int", False),
            C("fiscal_period", "str", False),
            C("account_code", "str", False),
            C("department_id", "str", False),
            C("cost_center_id", "str", False),
            C("budget_version", "str", False),
            C("scenario", "str", False),
            C("budget_amount", "money", False),
            C("currency", "str", False),
            C("approval_status", "str", False),
            C("approved_at", "ts"),
            *AUDIT_COLS,
        ),
        "Budget and forecast plan lines (sign: positive = planned amount in natural presentation).",
        delivery="excel",
        watermark=("updated_at",),
    )
)

# ---------------------------------------------------------------------------------------------- FX
_reg(
    TableContract(
        "fx",
        "exchange_rates",
        ("rate_date", "source_currency", "target_currency", "rate_type", "publication_timestamp"),
        (
            C("rate_date", "date", False),
            C("source_currency", "str", False),
            C("target_currency", "str", False),
            C("exchange_rate", "rate", False),
            C("rate_type", "str", False),
            C("provider", "str", False),
            C("publication_timestamp", "ts", False),
        ),
        "Published exchange rates: target units per one source unit. Corrections are re-publications.",
        delivery="csv",
        watermark=("publication_timestamp",),
    )
)


TABLES: dict[str, TableContract] = {t.fqn: t for t in _T}


def get(fqn: str) -> TableContract:
    return TABLES[fqn]


def tables_for(system: str) -> list[TableContract]:
    return [t for t in _T if t.system == system]
