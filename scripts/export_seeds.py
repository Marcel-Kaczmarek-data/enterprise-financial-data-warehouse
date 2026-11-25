"""Export reference data owned by group reporting into dbt seeds (single source of truth)."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_generator.chart_of_accounts import group_chart_rows  # noqa: E402

SEEDS = ROOT / "dbt_finance" / "seeds"


def write(name: str, rows: list[dict]) -> None:
    with (SEEDS / f"{name}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    SEEDS.mkdir(parents=True, exist_ok=True)
    write("group_chart_of_accounts", group_chart_rows())
    print("exported group_chart_of_accounts")
