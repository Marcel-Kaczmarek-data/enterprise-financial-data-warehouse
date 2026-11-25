"""Render docs/data-contracts.md from the contract registry (finance_common/contracts.py).

python scripts/generate_contract_docs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finance_common.contracts import _T, LOGICAL_TYPES  # noqa: E402


def main() -> None:
    out = [
        "# Source data contracts",
        "",
        "Generated from `finance_common/contracts.py` by `scripts/generate_contract_docs.py` - do not edit by hand.",
        "The same registry produces the generator's Parquet schemas, the PostgreSQL DDL of the simulated ERP,",
        "schema validation during ingestion and the dbt staging models.",
        "",
        f"{len(_T)} tables. Sensitivity classes: `PII`, `FINANCIAL_ACCOUNT`, `PAYROLL` (masked in Snowflake).",
        "",
    ]
    systems = sorted({t.system for t in _T})
    out += ["| System | Tables |", "|---|---|"]
    out += [f"| `{s}` | {', '.join(f'`{t.name}`' for t in _T if t.system == s)} |" for s in systems]
    for s in systems:
        out += ["", f"## `{s}`"]
        for t in (t for t in _T if t.system == s):
            out += [
                "",
                f"### `{t.fqn}`",
                "",
                t.description,
                "",
                f"- Primary key: `{', '.join(t.primary_key)}`  ",
                f"- Delivery: `{t.delivery}` · {'mutable (versions keyed by `updated_at`)' if t.mutable else 'append-only'}"
                f" · watermark `{', '.join(t.watermark)}`  ",
                f"- Owner: {t.owner}",
                "",
                "| Column | Type | Null | Sensitive | Description |",
                "|---|---|---|---|---|",
            ]
            out += [
                f"| `{c.name}` | {LOGICAL_TYPES[c.type][1]} | {'yes' if c.nullable else 'no'} | "
                f"{c.sensitive or ''} | {c.description} |"
                for c in t.columns
            ]
    target = ROOT / "docs" / "data-contracts.md"
    target.parent.mkdir(exist_ok=True)
    target.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)} ({len(_T)} tables)")


if __name__ == "__main__":
    main()
