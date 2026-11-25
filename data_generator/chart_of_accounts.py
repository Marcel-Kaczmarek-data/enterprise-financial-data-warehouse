"""Group chart of accounts (with hierarchy and statement mapping) and local entity charts of accounts.

Local charts differ by country: German entities use SKR04-style codes, French entities use PCG-style
codes and all other entities use the group code with a local suffix. Every local posting account is
mapped to exactly one group account (``erp.account_mappings``). Some group accounts are split into
several local accounts (domestic vs. export revenue, one cash account per bank account).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from data_generator.core import GeneratorError, at

# code, name, parent, account_type, account_category, statement_line, normal_balance, translation
# translation: CLOSING (balance sheet), AVERAGE (income statement), HISTORICAL (equity)
GROUP_ACCOUNTS: list[tuple[str, str, str | None, str, str, str | None, str, str]] = [
    ("1", "Assets", None, "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("11", "Current assets", "1", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("110", "Cash and cash equivalents", "11", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("1010", "Bank accounts", "110", "ASSET", "Assets", "Cash and cash equivalents", "DEBIT", "CLOSING"),
    ("120", "Receivables", "11", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("1100", "Accounts receivable - trade", "120", "ASSET", "Assets", "Accounts receivable", "DEBIT", "CLOSING"),
    ("1150", "Accounts receivable - intercompany", "120", "ASSET", "Assets", "Accounts receivable", "DEBIT", "CLOSING"),
    ("130", "Inventories", "11", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("1200", "Inventory - goods for resale", "130", "ASSET", "Assets", "Inventory", "DEBIT", "CLOSING"),
    ("140", "Prepayments and other current assets", "11", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("1300", "Prepaid expenses", "140", "ASSET", "Assets", "Prepaid expenses", "DEBIT", "CLOSING"),
    ("1400", "VAT receivable", "140", "ASSET", "Assets", "Other current assets", "DEBIT", "CLOSING"),
    ("15", "Non-current assets", "1", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("150", "Property, plant and equipment", "15", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("1500", "PP&E - acquisition cost", "150", "ASSET", "Assets", "Property, plant and equipment", "DEBIT", "CLOSING"),
    ("1590", "PP&E - accumulated depreciation", "150", "ASSET", "Assets", "Accumulated depreciation", "CREDIT", "CLOSING"),
    ("160", "Other non-current assets", "15", "ASSET", "Assets", None, "DEBIT", "CLOSING"),
    ("1600", "Long-term deposits", "160", "ASSET", "Assets", "Other non-current assets", "DEBIT", "CLOSING"),
    ("1700", "Investments in subsidiaries", "160", "ASSET", "Assets", "Other non-current assets", "DEBIT", "HISTORICAL"),
    ("2", "Liabilities", None, "LIABILITY", "Liabilities", None, "CREDIT", "CLOSING"),
    ("21", "Current liabilities", "2", "LIABILITY", "Liabilities", None, "CREDIT", "CLOSING"),
    ("210", "Trade payables", "21", "LIABILITY", "Liabilities", None, "CREDIT", "CLOSING"),
    ("2000", "Accounts payable - trade", "210", "LIABILITY", "Liabilities", "Accounts payable", "CREDIT", "CLOSING"),
    ("2050", "Accounts payable - intercompany", "210", "LIABILITY", "Liabilities", "Accounts payable", "CREDIT", "CLOSING"),
    ("220", "Accruals", "21", "LIABILITY", "Liabilities", None, "CREDIT", "CLOSING"),
    ("2100", "Accrued expenses", "220", "LIABILITY", "Liabilities", "Accrued expenses", "CREDIT", "CLOSING"),
    ("2300", "Salaries and reimbursements payable", "220", "LIABILITY", "Liabilities", "Accrued expenses", "CREDIT", "CLOSING"),
    ("230", "Tax liabilities", "21", "LIABILITY", "Liabilities", None, "CREDIT", "CLOSING"),
    ("2200", "VAT payable", "230", "LIABILITY", "Liabilities", "Tax liabilities", "CREDIT", "CLOSING"),
    ("2210", "Payroll taxes payable", "230", "LIABILITY", "Liabilities", "Tax liabilities", "CREDIT", "CLOSING"),
    ("2220", "Income tax payable", "230", "LIABILITY", "Liabilities", "Tax liabilities", "CREDIT", "CLOSING"),
    ("240", "Short-term debt", "21", "LIABILITY", "Liabilities", None, "CREDIT", "CLOSING"),
    ("2400", "Short-term borrowings", "240", "LIABILITY", "Liabilities", "Short-term debt", "CREDIT", "CLOSING"),
    ("25", "Non-current liabilities", "2", "LIABILITY", "Liabilities", None, "CREDIT", "CLOSING"),
    ("2500", "Long-term borrowings", "25", "LIABILITY", "Liabilities", "Long-term debt", "CREDIT", "CLOSING"),
    ("3", "Equity", None, "EQUITY", "Equity", None, "CREDIT", "HISTORICAL"),
    ("3000", "Share capital", "3", "EQUITY", "Equity", "Share capital", "CREDIT", "HISTORICAL"),
    ("3100", "Retained earnings", "3", "EQUITY", "Equity", "Retained earnings", "CREDIT", "HISTORICAL"),
    ("3200", "Currency translation reserve", "3", "EQUITY", "Equity", "Currency translation adjustments", "CREDIT", "HISTORICAL"),
    ("4", "Revenue", None, "REVENUE", "Revenue", None, "CREDIT", "AVERAGE"),
    ("4000", "Product revenue", "4", "REVENUE", "Revenue", "Product revenue", "CREDIT", "AVERAGE"),
    ("4100", "Service revenue", "4", "REVENUE", "Revenue", "Service revenue", "CREDIT", "AVERAGE"),
    ("4200", "Other operating revenue", "4", "REVENUE", "Revenue", "Other operating revenue", "CREDIT", "AVERAGE"),
    ("4500", "Intercompany service revenue", "4", "REVENUE", "Revenue", "Other operating revenue", "CREDIT", "AVERAGE"),
    ("5", "Cost of goods sold", None, "EXPENSE", "Cost of goods sold", None, "DEBIT", "AVERAGE"),
    ("5000", "Cost of goods sold", "5", "EXPENSE", "Cost of goods sold", "Cost of goods sold", "DEBIT", "AVERAGE"),
    ("6", "Operating expenses", None, "EXPENSE", "Operating expenses", None, "DEBIT", "AVERAGE"),
    ("6000", "Salaries and wages", "6", "EXPENSE", "Operating expenses", "Salaries and benefits", "DEBIT", "AVERAGE"),
    ("6050", "Employer social contributions", "6", "EXPENSE", "Operating expenses", "Salaries and benefits", "DEBIT", "AVERAGE"),
    ("6100", "Software and cloud services", "6", "EXPENSE", "Operating expenses", "Technology expenses", "DEBIT", "AVERAGE"),
    ("6150", "IT hardware and telecom", "6", "EXPENSE", "Operating expenses", "Technology expenses", "DEBIT", "AVERAGE"),
    ("6200", "Advertising and marketing", "6", "EXPENSE", "Operating expenses", "Marketing expenses", "DEBIT", "AVERAGE"),
    ("6300", "Rent", "6", "EXPENSE", "Operating expenses", "Rent and utilities", "DEBIT", "AVERAGE"),
    ("6350", "Utilities", "6", "EXPENSE", "Operating expenses", "Rent and utilities", "DEBIT", "AVERAGE"),
    ("6400", "Office and administrative", "6", "EXPENSE", "Operating expenses", "Administrative expenses", "DEBIT", "AVERAGE"),
    ("6420", "Bad debt expense", "6", "EXPENSE", "Operating expenses", "Administrative expenses", "DEBIT", "AVERAGE"),
    ("6450", "Bank charges", "6", "EXPENSE", "Operating expenses", "Administrative expenses", "DEBIT", "AVERAGE"),
    ("6500", "Travel and entertainment", "6", "EXPENSE", "Operating expenses", "Travel expenses", "DEBIT", "AVERAGE"),
    ("6600", "Legal and professional fees", "6", "EXPENSE", "Operating expenses", "Professional services", "DEBIT", "AVERAGE"),
    ("6650", "Intercompany management fees", "6", "EXPENSE", "Operating expenses", "Administrative expenses", "DEBIT", "AVERAGE"),
    ("7", "Depreciation and amortization", None, "EXPENSE", "Operating expenses", None, "DEBIT", "AVERAGE"),
    ("7000", "Depreciation expense", "7", "EXPENSE", "Operating expenses", "Depreciation and amortization", "DEBIT", "AVERAGE"),
    ("8", "Financial and other items", None, "EXPENSE", "Other expenses", None, "DEBIT", "AVERAGE"),
    ("8000", "Interest income", "8", "REVENUE", "Other income", "Finance income", "CREDIT", "AVERAGE"),
    ("8100", "Interest expense", "8", "EXPENSE", "Other expenses", "Finance expenses", "DEBIT", "AVERAGE"),
    ("8200", "Foreign exchange gains and losses", "8", "EXPENSE", "Other expenses", "Other non-operating items", "DEBIT", "AVERAGE"),
    ("8300", "Early payment discounts received", "8", "REVENUE", "Other income", "Other non-operating items", "CREDIT", "AVERAGE"),
    ("8350", "Gain or loss on asset disposals", "8", "EXPENSE", "Other expenses", "Other non-operating items", "DEBIT", "AVERAGE"),
    ("9", "Taxes", None, "EXPENSE", "Tax expenses", None, "DEBIT", "AVERAGE"),
    ("9000", "Income tax expense", "9", "EXPENSE", "Tax expenses", "Income tax expense", "DEBIT", "AVERAGE"),
]
GROUP_BY_CODE = {g[0]: g for g in GROUP_ACCOUNTS}
POSTING_CODES = [g[0] for g in GROUP_ACCOUNTS if len(g[0]) == 4]

SKR04 = {  # German-style local codes (SKR04-like, simplified)
    "1010": "1800", "1100": "1200", "1150": "1260", "1200": "1140", "1300": "1900", "1400": "1406",
    "1500": "0400", "1590": "0490", "1600": "0960", "1700": "0800", "2000": "3300", "2050": "3360",
    "2100": "3070", "2300": "3720", "2200": "3806", "2210": "3730", "2220": "3040", "2400": "3150",
    "2500": "3160", "3000": "2900", "3100": "2970", "4000": "4400", "4100": "4500", "4200": "4830",
    "4500": "4870", "5000": "5400", "6000": "6020", "6050": "6110", "6100": "6837", "6150": "6810",
    "6200": "6600", "6300": "6310", "6350": "6325", "6400": "6815", "6420": "6930", "6450": "6855",
    "6500": "6650", "6600": "6825", "6650": "6304", "7000": "6220", "8000": "7100", "8100": "7300",
    "8200": "6880", "8300": "7130", "8350": "6895", "9000": "7600",
}
PCG = {  # French-style local codes (Plan Comptable Général-like, simplified)
    "1010": "512", "1100": "411", "1150": "451", "1200": "370", "1300": "486", "1400": "44566",
    "1500": "218", "1590": "2818", "1600": "275", "1700": "261", "2000": "401", "2050": "4510",
    "2100": "4286", "2300": "421", "2200": "44571", "2210": "431", "2220": "444", "2400": "519",
    "2500": "164", "3000": "101", "3100": "110", "4000": "707", "4100": "706", "4200": "708",
    "4500": "7062", "5000": "607", "6000": "641", "6050": "645", "6100": "6156", "6150": "6064",
    "6200": "623", "6300": "613", "6350": "6061", "6400": "606", "6420": "654", "6450": "627",
    "6500": "625", "6600": "622", "6650": "6226", "7000": "6811", "8000": "768", "8100": "661",
    "8200": "666", "8300": "765", "8350": "675", "9000": "695",
}
SPLIT_BY_MARKET = ("4000", "4100")  # domestic vs export revenue accounts

ENTITY_ACCOUNT_USAGE = {
    "HOLDING": {"1010", "1150", "1300", "1400", "1600", "1700", "2000", "2050", "2100", "2300", "2200", "2210",
                "2220", "2500", "3000", "3100", "4500", "6000", "6050", "6100", "6300", "6350", "6400", "6450",
                "6500", "6600", "7000", "8000", "8100", "8200", "8300", "1500", "1590", "8350", "9000",
                "6150", "6200"},
}


@dataclass
class ChartOfAccounts:
    accounts: list[dict]
    mappings: list[dict]
    _lookup: dict[tuple[str, str, str | None], int]
    _default: dict[tuple[str, str], int]

    def account_for(self, entity_id: str, group_code: str, variant: str | None = None) -> int:
        key = (entity_id, group_code, variant)
        if key in self._lookup:
            return self._lookup[key]
        if (entity_id, group_code) in self._default:
            return self._default[(entity_id, group_code)]
        raise GeneratorError(f"no local account for {entity_id} / {group_code} / {variant}")


def _local_code(country: str, group_code: str, suffix: int) -> str:
    if country == "DE":
        return SKR04[group_code] + (f"{suffix}" if suffix else "")
    if country == "FR":
        return PCG[group_code] + (f"{suffix:02d}" if suffix else "")
    return f"{group_code}{suffix:02d}"


def build_chart_of_accounts(entities: list, bank_accounts: dict[str, list[dict]], start: date) -> ChartOfAccounts:
    created = at(date(start.year - 1, 10, 15))
    accounts: list[dict] = []
    mappings: list[dict] = []
    lookup: dict[tuple[str, str, str | None], int] = {}
    default: dict[tuple[str, str], int] = {}
    next_id = 100000

    def add(entity, group_code: str, suffix: int, name: str, variant: str | None, bank_id: str | None) -> int:
        nonlocal next_id
        next_id += 1
        g = GROUP_BY_CODE[group_code]
        accounts.append({
            "account_id": next_id, "entity_id": entity.entity_id,
            "account_code": _local_code(entity.country, group_code, suffix), "account_name": name,
            "account_type": g[3], "account_category": g[4], "parent_account_id": None,
            "reporting_group": g[5], "normal_balance": g[6], "account_status": "ACTIVE",
            "bank_account_id": bank_id, "created_at": created, "updated_at": created,
        })
        mappings.append({
            "mapping_id": len(mappings) + 1, "account_id": next_id, "entity_id": entity.entity_id,
            "group_account_code": group_code, "valid_from": date(2015, 1, 1), "valid_to": None,
            "mapping_version": "GCOA-2015.1", "created_at": created, "updated_at": created,
        })
        lookup[(entity.entity_id, group_code, variant)] = next_id
        default.setdefault((entity.entity_id, group_code), next_id)
        return next_id

    for e in entities:
        usage = ENTITY_ACCOUNT_USAGE.get(e.entity_type)
        if e.entity_type == "REGIONAL_HOLDING":
            usage = ENTITY_ACCOUNT_USAGE["HOLDING"]
        for code in POSTING_CODES:
            if code == "3200":
                continue  # consolidation-only account (CTA), never posted locally
            if usage is not None and code not in usage:
                continue
            if e.entity_type == "SHARED_SERVICES" and code in ("4000", "4100", "1200", "5000", "1700"):
                continue
            if e.entity_type == "OPERATING" and code == "1700" and e.entity_id not in ("E09",):
                continue
            g = GROUP_BY_CODE[code]
            if code == "1010":
                for i, ba in enumerate(bank_accounts[e.entity_id], start=1):
                    acc_id = add(e, code, i, f"Bank {ba['bank_name']} {ba['currency']} {ba['account_purpose'].title()}",
                                 ba["bank_account_id"], ba["bank_account_id"])
                    ba["gl_account_id"] = acc_id
                continue
            if code in SPLIT_BY_MARKET and e.entity_type == "OPERATING":
                add(e, code, 10, f"{g[1]} - domestic", "domestic", None)
                add(e, code, 20, f"{g[1]} - export", "export", None)
                continue
            add(e, code, 0, g[1], None, None)
    return ChartOfAccounts(accounts, mappings, lookup, default)


def group_chart_rows() -> list[dict]:
    """Rows for the dbt seed ``group_chart_of_accounts`` (hierarchy + statement mapping)."""
    rows = []
    for code, name, parent, a_type, cat, line, normal, translation in GROUP_ACCOUNTS:
        level = {1: 1, 2: 2, 3: 3, 4: 4}[len(code)]
        rows.append({
            "group_account_code": code, "group_account_name": name, "parent_group_account_code": parent or "",
            "hierarchy_level": level, "account_type": a_type, "account_category": cat,
            "statement": "BALANCE_SHEET" if code[0] in "123" else "INCOME_STATEMENT",
            "statement_line": line or "", "normal_balance": normal, "translation_method": translation,
            "is_posting_account": len(code) == 4,
        })
    return rows
