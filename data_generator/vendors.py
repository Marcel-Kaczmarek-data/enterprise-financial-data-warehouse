"""Supplier master, including intercompany suppliers representing group entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from data_generator.core import at, rng_for
from data_generator.customers import PREFIX, SUFFIX

CATEGORIES = [
    # category, share of vendors, expense group code, uses purchase orders
    ("INVENTORY", 0.22, "1200", True),
    ("SOFTWARE", 0.12, "6100", False),
    ("IT_HARDWARE", 0.08, "6150", True),
    ("MARKETING", 0.12, "6200", False),
    ("RENT", 0.05, "6300", False),
    ("UTILITIES", 0.05, "6350", False),
    ("OFFICE", 0.12, "6400", False),
    ("TRAVEL", 0.08, "6500", False),
    ("PROFESSIONAL", 0.11, "6600", False),
    ("CAPEX", 0.05, "1500", True),
]
CATEGORY_ACCOUNT = {c[0]: c[2] for c in CATEGORIES}
CATEGORY_USES_PO = {c[0]: c[3] for c in CATEGORIES}
CORE = {"INVENTORY": ["Components", "Electronics", "Distribution", "Supply"],
        "SOFTWARE": ["Cloud", "Software", "SaaS", "Data"], "IT_HARDWARE": ["IT Solutions", "Devices", "Networks"],
        "MARKETING": ["Media", "Creative", "Events", "Digital"], "RENT": ["Properties", "Real Estate", "Estates"],
        "UTILITIES": ["Power", "Energy", "Utilities"], "OFFICE": ["Office Supplies", "Facilities", "Services"],
        "TRAVEL": ["Travel", "Mobility", "Hotels"], "PROFESSIONAL": ["Advisory", "Legal", "Consulting", "Audit"],
        "CAPEX": ["Machinery", "Equipment", "Fit-Out"]}
FOREIGN_SUPPLY = {"INVENTORY": [("CN", "CNY"), ("US", "USD")], "SOFTWARE": [("US", "USD")]}


@dataclass
class Vendor:
    vendor_id: int
    entity_scope: str  # entity that mainly buys from this vendor
    category: str
    country: str
    currency: str
    terms: int
    discount_pct: Decimal | None
    discount_days: int | None
    name: str
    late_payer_flag: bool
    is_intercompany: bool = False
    ic_entity_id: str | None = None


def _pick(rng, options):
    r, acc = rng.random(), 0.0
    for opt in options:
        acc += opt[1]
        if r <= acc:
            return opt
    return options[-1]


def build_vendors(ctx: Any, n_vendors: int) -> tuple[list[Vendor], dict[tuple[str, str], list[Vendor]]]:
    rng = rng_for(ctx.seed, "vendors")
    entities = ctx.entity_list
    vendors: list[Vendor] = []
    by_entity_cat: dict[tuple[str, str], list[Vendor]] = {}
    # Guarantee each entity has at least one vendor in each relevant category.
    required = []
    for e in entities:
        for cat, *_ in CATEGORIES:
            if cat == "INVENTORY" and e.entity_type != "OPERATING":
                continue
            required.append((e, cat))
    for i in range(1, max(n_vendors, len(required)) + 1):
        if i <= len(required):
            e, cat = required[i - 1]
        else:
            e = rng.choice(entities)
            cat = _pick(rng, CATEGORIES)[0]
            if cat == "INVENTORY" and e.entity_type != "OPERATING":
                cat = "OFFICE"
        country, ccy = e.country, e.functional_currency
        if cat in FOREIGN_SUPPLY and rng.random() < 0.3:
            country, ccy = rng.choice(FOREIGN_SUPPLY[cat])
            if not ctx.treasury.has_currency(e.entity_id, ccy) and ccy != e.functional_currency:
                country, ccy = e.country, e.functional_currency
        discount = rng.random() < 0.15
        v = Vendor(i, e.entity_id, cat, country, ccy, rng.choice([14, 30, 30, 45, 60]),
                   Decimal("2.0") if discount else None, 10 if discount else None,
                   f"{rng.choice(PREFIX)} {rng.choice(CORE[cat])} {SUFFIX.get(country, 'Co., Ltd.')}",
                   rng.random() < 0.05)
        vendors.append(v)
        by_entity_cat.setdefault((e.entity_id, cat), []).append(v)

    hist_rng = rng_for(ctx.seed, "vendor-history")
    for v in vendors:
        created = at(ctx.start - timedelta(days=hist_rng.randint(30, 1500)), 9)
        _emit(ctx, v, created, created)
        if hist_rng.random() < 0.08:  # payment-terms renegotiation -> captured by dbt snapshot
            changed = at(ctx.start + timedelta(days=hist_rng.randint(100, (ctx.end - ctx.start).days - 30)), 13)
            v.terms = 60 if v.terms < 60 else 45
            _emit(ctx, v, created, changed)
    return vendors, by_entity_cat


def build_intercompany_vendors(ctx: Any, start_id: int) -> dict[tuple[str, str], Vendor]:
    """Supplier records in the buyer's ERP representing a group seller entity."""
    out: dict[tuple[str, str], Vendor] = {}
    created = at(date(ctx.start.year - 1, 10, 25))
    for n, (seller, buyer, ccy) in enumerate(ctx.ic_relationships, start=1):
        s = ctx.entities[seller]
        v = Vendor(start_id + n, buyer, "INTERCOMPANY", s.country, ccy, 30, None, None, s.entity_name, False,
                   True, seller)
        out[(seller, buyer)] = v
        _emit(ctx, v, created, created)
    return out


def _emit(ctx: Any, v: Vendor, created, updated) -> None:
    ctx.sink.emit("erp.vendors", {
        "vendor_id": v.vendor_id, "vendor_number": f"V{v.vendor_id:06d}", "vendor_name": v.name,
        "vendor_category": v.category, "country": v.country, "currency": v.currency,
        "payment_terms_days": v.terms, "early_payment_discount_pct": v.discount_pct,
        "early_payment_discount_days": v.discount_days,
        "bank_account_masked": f"{v.country}** **** **** {v.vendor_id * 31 % 10000:04d}",
        "tax_id": f"{v.country}VAT{v.vendor_id * 104729 % 10**9:09d}", "vendor_status": "ACTIVE",
        "is_intercompany": v.is_intercompany, "intercompany_entity_id": v.ic_entity_id,
        "created_at": created, "updated_at": updated,
    })
