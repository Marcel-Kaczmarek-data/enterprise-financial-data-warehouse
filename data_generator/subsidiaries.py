"""Legal entities, countries, departments, cost centers, profit centers and products.

The group ("Halcyon Group", fictitious) is a multinational technology hardware/software company.
All subsidiaries are wholly owned (100%) – partial ownership / NCI is a documented extension.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from data_generator.core import at, rng_for

COUNTRIES: dict[str, tuple[str, str, str]] = {
    # code: (name, region, currency)
    "NL": ("Netherlands", "Europe", "EUR"),
    "DE": ("Germany", "Europe", "EUR"),
    "FR": ("France", "Europe", "EUR"),
    "IE": ("Ireland", "Europe", "EUR"),
    "GB": ("United Kingdom", "Europe", "GBP"),
    "CH": ("Switzerland", "Europe", "CHF"),
    "SE": ("Sweden", "Europe", "SEK"),
    "US": ("United States", "North America", "USD"),
    "CA": ("Canada", "North America", "CAD"),
    "JP": ("Japan", "Asia", "JPY"),
    "SG": ("Singapore", "Asia", "SGD"),
    "IN": ("India", "Asia", "INR"),
}
CURRENCIES = ["EUR", "GBP", "USD", "CAD", "JPY", "SGD", "INR", "CHF", "SEK", "CNY"]


@dataclass(frozen=True)
class EntitySpec:
    entity_id: str
    entity_name: str
    country: str
    parent_entity_id: str | None
    entity_type: str  # HOLDING | REGIONAL_HOLDING | OPERATING | SHARED_SERVICES
    sales_weight: float
    fiscal_calendar: str = "GREGORIAN"

    @property
    def functional_currency(self) -> str:
        return COUNTRIES[self.country][2]

    @property
    def region(self) -> str:
        return COUNTRIES[self.country][1]


ENTITIES: list[EntitySpec] = [
    EntitySpec("E01", "Halcyon Group Holding B.V.", "NL", None, "HOLDING", 0.0),
    EntitySpec("E02", "Halcyon Deutschland GmbH", "DE", "E01", "OPERATING", 1.6),
    EntitySpec("E03", "Halcyon Industrial Systems GmbH", "DE", "E01", "OPERATING", 1.0),
    EntitySpec("E04", "Halcyon France SAS", "FR", "E01", "OPERATING", 1.1),
    EntitySpec("E05", "Halcyon Ireland Ltd", "IE", "E01", "OPERATING", 0.6),
    EntitySpec("E06", "Halcyon UK Ltd", "GB", "E01", "OPERATING", 1.3),
    EntitySpec("E07", "Halcyon Schweiz AG", "CH", "E01", "OPERATING", 0.5),
    EntitySpec("E08", "Halcyon Sverige AB", "SE", "E01", "OPERATING", 0.5),
    EntitySpec("E09", "Halcyon Americas Inc.", "US", "E01", "OPERATING", 2.0),
    EntitySpec("E10", "Halcyon US Shared Services LLC", "US", "E09", "SHARED_SERVICES", 0.0),
    EntitySpec("E11", "Halcyon Canada Ltd", "CA", "E09", "OPERATING", 0.6),
    EntitySpec("E12", "Halcyon Japan K.K.", "JP", "E15", "OPERATING", 0.8),
    EntitySpec("E13", "Halcyon Singapore Pte. Ltd.", "SG", "E15", "OPERATING", 0.6),
    EntitySpec("E14", "Halcyon India Pvt. Ltd.", "IN", "E15", "OPERATING", 0.7, "APR_MAR"),
    EntitySpec("E15", "Halcyon Asia Pacific Holdings Pte. Ltd.", "SG", "E01", "REGIONAL_HOLDING", 0.0),
]
ENTITY_BY_ID = {e.entity_id: e for e in ENTITIES}

DEPARTMENTS: list[tuple[str, str, str]] = [
    # id, name, functional area (drives P&L function and payroll mix)
    ("D01", "Manufacturing Operations", "OPERATIONS"),
    ("D02", "Supply Chain", "OPERATIONS"),
    ("D03", "Logistics", "OPERATIONS"),
    ("D04", "Customer Support", "OPERATIONS"),
    ("D05", "Professional Services Delivery", "OPERATIONS"),
    ("D06", "Enterprise Sales", "SALES"),
    ("D07", "Commercial Sales", "SALES"),
    ("D08", "Channel Partners", "SALES"),
    ("D09", "Sales Operations", "SALES"),
    ("D10", "Brand Marketing", "MARKETING"),
    ("D11", "Digital Marketing", "MARKETING"),
    ("D12", "Product Marketing", "MARKETING"),
    ("D13", "Engineering", "R&D"),
    ("D14", "Product Management", "R&D"),
    ("D15", "Data & Analytics", "R&D"),
    ("D16", "Quality Assurance", "R&D"),
    ("D17", "Finance", "G&A"),
    ("D18", "Treasury", "G&A"),
    ("D19", "Legal", "G&A"),
    ("D20", "Human Resources", "G&A"),
    ("D21", "Information Technology", "G&A"),
    ("D22", "Facilities", "G&A"),
    ("D23", "Procurement", "G&A"),
    ("D24", "Executive Office", "G&A"),
    ("D25", "Internal Audit", "G&A"),
]

CORE_DEPTS = {
    "HOLDING": ["D17", "D18", "D19", "D24", "D25"],
    "REGIONAL_HOLDING": ["D17", "D18", "D24"],
    "SHARED_SERVICES": ["D21", "D17", "D20", "D15", "D13"],
    "OPERATING": ["D17", "D20", "D06", "D07", "D04", "D11"],
}
EXTRA_DEPT_PRIORITY = [
    "D13",
    "D05",
    "D02",
    "D21",
    "D10",
    "D22",
    "D01",
    "D14",
    "D08",
    "D12",
    "D09",
    "D23",
    "D03",
    "D16",
    "D19",
]

PRODUCT_LINES = [
    # line, revenue type, standard cost ratio, (min, max) base list price EUR
    ("Hardware", "PRODUCT", Decimal("0.58"), (800, 12000)),
    ("Software Licenses", "PRODUCT", Decimal("0.14"), (1500, 30000)),
    ("Professional Services", "SERVICE", Decimal("0"), (1200, 9000)),
    ("Managed Services", "SERVICE", Decimal("0"), (2000, 16000)),
]
PRODUCT_NAMES = {
    "Hardware": [
        "Edge Gateway X1",
        "Edge Gateway X2",
        "Sensor Array S4",
        "Rack Controller R8",
        "Industrial Router IR5",
        "Secure Appliance SA3",
        "Storage Node N12",
        "Compute Module C7",
        "Power Unit P2",
        "Display Panel D9",
        "Field Terminal F3",
        "Network Switch W24",
    ],
    "Software Licenses": [
        "Fleet Analytics",
        "Asset Monitor",
        "Edge OS Enterprise",
        "Security Suite",
        "Data Connector Pack",
        "Workflow Studio",
        "Forecast Engine",
        "Compliance Vault",
        "Identity Hub",
        "Device Manager",
        "Insight Dashboards",
        "API Gateway",
    ],
    "Professional Services": [
        "Implementation Day Rate",
        "Solution Architecture",
        "Data Migration",
        "Integration Sprint",
        "Training Workshop",
        "Health Check",
        "Security Assessment",
        "Project Management",
        "Custom Development",
        "Go-Live Support",
        "Process Consulting",
        "Advisory Retainer",
    ],
    "Managed Services": [
        "Managed Edge Basic",
        "Managed Edge Pro",
        "24x7 Monitoring",
        "Managed Security",
        "Cloud Hosting Small",
        "Cloud Hosting Large",
        "Backup Service",
        "Service Desk",
        "Patch Management",
        "Capacity Planning",
        "Managed Analytics",
        "Premium Support",
    ],
}


@dataclass
class Org:
    departments: list[dict]
    cost_centers: list[dict]
    profit_centers: list[dict]
    products: list[dict]
    cost_center_department: dict[str, str]
    entity_cost_centers: dict[str, list[str]]
    entity_profit_centers: dict[str, dict[str, str]]  # entity -> product_line -> pc
    cc_by_entity_dept: dict[tuple[str, str], str]

    def cc(self, entity_id: str, *dept_preference: str) -> str:
        for d in dept_preference:
            cc = self.cc_by_entity_dept.get((entity_id, d))
            if cc:
                return cc
        return self.entity_cost_centers[entity_id][0]


def build_org(seed: int, start: date, n_cost_centers: int, n_profit_centers: int) -> Org:
    created = at(date(start.year - 1, 11, 1))
    departments = [
        {"department_id": d, "department_name": n, "functional_area": f, "created_at": created, "updated_at": created}
        for d, n, f in DEPARTMENTS
    ]
    pairs: list[tuple[str, str]] = []
    for e in ENTITIES:
        pairs += [(e.entity_id, d) for d in CORE_DEPTS[e.entity_type]]
    operating = sorted([e for e in ENTITIES if e.entity_type == "OPERATING"], key=lambda e: -e.sales_weight)
    extra = [(e.entity_id, d) for d in EXTRA_DEPT_PRIORITY for e in operating]
    for p in extra:
        if len(pairs) >= n_cost_centers:
            break
        if p not in pairs:
            pairs.append(p)
    cost_centers, cc_dept, ent_cc, cc_map = [], {}, {}, {}
    dept_name = {d: n for d, n, _ in DEPARTMENTS}
    for i, (eid, d) in enumerate(pairs, start=1):
        cc_id = f"CC{i:03d}"
        cost_centers.append(
            {
                "cost_center_id": cc_id,
                "cost_center_name": f"{eid} {dept_name[d]}",
                "entity_id": eid,
                "department_id": d,
                "manager_employee_id": None,
                "is_active": True,
                "created_at": created,
                "updated_at": created,
            }
        )
        cc_dept[cc_id] = d
        ent_cc.setdefault(eid, []).append(cc_id)
        cc_map[(eid, d)] = cc_id

    # Profit centers: every operating entity gets Hardware, then fill by entity weight / product line.
    pc_pairs = [(e.entity_id, "Hardware") for e in operating]
    for line, *_ in PRODUCT_LINES[1:] + PRODUCT_LINES[:1]:
        for e in operating:
            if len(pc_pairs) >= n_profit_centers:
                break
            if (e.entity_id, line) not in pc_pairs:
                pc_pairs.append((e.entity_id, line))
    profit_centers, ent_pc = [], {}
    for i, (eid, line) in enumerate(pc_pairs, start=1):
        pc_id = f"PC{i:03d}"
        profit_centers.append(
            {
                "profit_center_id": pc_id,
                "profit_center_name": f"{eid} {line}",
                "entity_id": eid,
                "product_line": line,
                "created_at": created,
                "updated_at": created,
            }
        )
        ent_pc.setdefault(eid, {})[line] = pc_id

    rng = rng_for(seed, "products")
    products = []
    for li, (line, rev_type, cost_ratio, (lo, hi)) in enumerate(PRODUCT_LINES, start=1):
        for pi, name in enumerate(PRODUCT_NAMES[line], start=1):
            products.append(
                {
                    "product_id": f"P{li}{pi:02d}",
                    "product_name": name,
                    "product_line": line,
                    "revenue_type": rev_type,
                    "list_price_eur": Decimal(rng.randrange(lo, hi, 50)),
                    "standard_cost_ratio": cost_ratio,
                    "created_at": created,
                    "updated_at": created,
                }
            )
    return Org(departments, cost_centers, profit_centers, products, cc_dept, ent_cc, ent_pc, cc_map)


def legal_entity_rows(start: date) -> list[dict]:
    created = at(date(start.year - 1, 10, 1))
    return [
        {
            "entity_id": e.entity_id,
            "parent_entity_id": e.parent_entity_id,
            "entity_name": e.entity_name,
            "country": e.country,
            "functional_currency": e.functional_currency,
            "reporting_currency": "EUR",
            "fiscal_calendar": e.fiscal_calendar,
            "ownership_percentage": Decimal("100"),
            "entity_type": e.entity_type,
            "effective_from": date(2015, 1, 1) if e.parent_entity_id else date(2010, 1, 1),
            "effective_to": None,
            "created_at": created,
            "updated_at": created,
        }
        for e in ENTITIES
    ]
