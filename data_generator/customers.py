"""CRM customers (with field history) and ERP customer accounts (cross-system key mapping)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import at, rng_for
from data_generator.subsidiaries import COUNTRIES

PREFIX = ["Apex", "Blue", "Cedar", "Delta", "Ember", "Falcon", "Granite", "Harbor", "Iris", "Juniper", "Keystone",
          "Lumen", "Maple", "Nimbus", "Orion", "Pioneer", "Quartz", "Riverside", "Summit", "Tidal", "Union",
          "Vertex", "Willow", "Xenon", "Yarrow", "Zenith", "Atlas", "Beacon", "Cobalt", "Drift", "Evergreen",
          "Frontier", "Golden", "Highland", "Ironwood", "Jade", "Kestrel", "Lakeside", "Monarch", "Northwind"]
CORE = ["Logistics", "Manufacturing", "Retail", "Health", "Energy", "Foods", "Mobility", "Systems", "Analytics",
        "Pharma", "Utilities", "Construction", "Telecom", "Insurance", "Media", "Aerospace", "Textiles",
        "Chemicals", "Agritech", "Marine"]
SUFFIX = {"DE": "GmbH", "FR": "SAS", "NL": "B.V.", "IE": "Ltd", "GB": "Ltd", "CH": "AG", "SE": "AB", "US": "Inc.",
          "CA": "Ltd", "JP": "K.K.", "SG": "Pte. Ltd.", "IN": "Pvt. Ltd."}
INDUSTRY = {"Logistics": "Transportation", "Manufacturing": "Industrial", "Retail": "Retail", "Health": "Healthcare",
            "Energy": "Energy", "Foods": "Consumer Goods", "Mobility": "Automotive", "Systems": "Technology",
            "Analytics": "Technology", "Pharma": "Life Sciences", "Utilities": "Utilities",
            "Construction": "Construction", "Telecom": "Telecommunications", "Insurance": "Financial Services",
            "Media": "Media", "Aerospace": "Industrial", "Textiles": "Consumer Goods", "Chemicals": "Industrial",
            "Agritech": "Agriculture", "Marine": "Transportation"}
SEGMENTS = [("Enterprise", 0.10, 6.0), ("Mid-Market", 0.30, 2.0), ("SMB", 0.55, 0.55), ("Public Sector", 0.05, 3.0)]
BEHAVIOR = [("PROMPT", 0.45), ("NORMAL", 0.35), ("LATE", 0.15), ("DELINQUENT", 0.05)]
NEIGHBOURS = {"DE": ["NL", "FR", "CH"], "FR": ["DE", "IE"], "NL": ["DE"], "IE": ["GB"], "GB": ["IE", "US"],
              "CH": ["DE", "FR"], "SE": ["DE", "NL"], "US": ["CA", "GB"], "CA": ["US"], "JP": ["SG"],
              "SG": ["IN", "JP"], "IN": ["SG"]}


@dataclass
class Customer:
    customer_id: int
    home_entity_id: str
    country: str
    segment: str
    size_factor: float
    behavior: str
    batch_payer: bool
    weight: float
    erp_customer_id: int
    billing_currency: str
    payment_terms_days: int
    name: str


def _pick(rng, options):
    r, acc = rng.random(), 0.0
    for opt in options:
        acc += opt[1]
        if r <= acc:
            return opt
    return options[-1]


def build_customers(ctx: Any, n_customers: int) -> list[Customer]:
    rng = rng_for(ctx.seed, "customers")
    operating = [e for e in ctx.entity_list if e.entity_type == "OPERATING"]
    total_w = sum(e.sales_weight for e in operating)
    customers: list[Customer] = []
    for i in range(1, n_customers + 1):
        r, acc, home = rng.random() * total_w, 0.0, operating[-1]
        for e in operating:
            acc += e.sales_weight
            if r <= acc:
                home = e
                break
        country = home.country
        if rng.random() < 0.12:
            country = rng.choice(NEIGHBOURS[home.country])
        seg, _, size = _pick(rng, SEGMENTS)
        behavior = _pick(rng, BEHAVIOR)[0]
        fc = home.functional_currency
        cust_ccy = COUNTRIES[country][2]
        billing = cust_ccy if cust_ccy in ("EUR", "USD") and cust_ccy != fc else fc
        terms = {"Enterprise": 60, "Public Sector": 45, "Mid-Market": 45, "SMB": 30}[seg]
        name = f"{rng.choice(PREFIX)} {rng.choice(CORE)} {SUFFIX[country]}"
        weight = size * (1.0 / (1 + (i % 97) / 12))  # long tail -> realistic concentration
        customers.append(Customer(i, home.entity_id, country, seg, size, behavior, rng.random() < 0.2, weight,
                                  500000 + i, billing, terms, name))

    start = ctx.start
    hist_rng = rng_for(ctx.seed, "customer-history")
    for c in customers:
        created = at(start - timedelta(days=hist_rng.randint(30, 2000)), 9)
        industry = INDUSTRY[c.name.split(" ")[1]]
        versions = [(created, c.segment, "ACTIVE", "Customer created")]
        if hist_rng.random() < 0.12:  # segment change -> SCD2 history
            change_day = start + timedelta(days=hist_rng.randint(120, (ctx.end - start).days - 30))
            new_seg = {"SMB": "Mid-Market", "Mid-Market": "Enterprise", "Enterprise": "Enterprise",
                       "Public Sector": "Public Sector"}[c.segment]
            if new_seg != c.segment:
                versions.append((at(change_day, 14), new_seg, "ACTIVE", "Segment reclassification"))
        if c.behavior == "DELINQUENT" and hist_rng.random() < 0.3:
            change_day = start + timedelta(days=hist_rng.randint(400, (ctx.end - start).days - 10))
            versions.append((at(change_day, 15), versions[-1][1], "CREDIT_HOLD", "Credit hold after overdue balance"))
        versions.sort()
        for v_from, seg, status, reason in versions:
            ctx.sink.emit("crm.customer_history", {
                "customer_id": c.customer_id, "valid_from": v_from, "segment": seg, "industry": industry,
                "country": c.country, "customer_status": status, "change_reason": reason,
                "created_at": v_from, "updated_at": v_from,
            })
            ctx.sink.emit("crm.customers", {  # one version per change (state-as-of seeding)
                "customer_id": c.customer_id, "customer_number": f"C{c.customer_id:07d}", "customer_name": c.name,
                "segment": seg, "industry": industry, "country": c.country, "home_entity_id": c.home_entity_id,
                "contact_email": f"accounts.payable+{c.customer_id}@customer.example",
                "tax_id": f"{c.country}TX{c.customer_id * 7919 % 10**9:09d}", "customer_status": status,
                "created_at": created, "updated_at": v_from,
            })
        ctx.sink.emit("erp.customer_accounts", {
            "erp_customer_id": c.erp_customer_id, "crm_customer_id": c.customer_id, "entity_id": c.home_entity_id,
            "intercompany_entity_id": None, "payment_terms_days": c.payment_terms_days,
            "credit_limit": Decimal(int(250000 * c.size_factor)), "billing_currency": c.billing_currency,
            "created_at": created, "updated_at": created,
        })
    return customers


def build_intercompany_customer_accounts(ctx: Any) -> dict[tuple[str, str], int]:
    """ERP customer accounts used by a seller entity to invoice a group entity (no CRM customer)."""
    out: dict[tuple[str, str], int] = {}
    created = at(date(ctx.start.year - 1, 10, 25))
    n = 0
    for seller, buyer, ccy in ctx.ic_relationships:
        n += 1
        erp_id = 900000 + n
        out[(seller, buyer)] = erp_id
        ctx.sink.emit("erp.customer_accounts", {
            "erp_customer_id": erp_id, "crm_customer_id": None, "entity_id": seller,
            "intercompany_entity_id": buyer, "payment_terms_days": 30, "credit_limit": None,
            "billing_currency": ccy, "created_at": created, "updated_at": created,
        })
    return out
