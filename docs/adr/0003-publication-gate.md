# ADR 0003: A publication gate in front of every report

**Status:** accepted

## Context
Finance users must never see figures from a build where a critical control failed, such as unbalanced
journals, a broken balance-sheet equation or a missing exchange rate.

## Decision
Dashboards read only a **published snapshot**, a read-only copy of the warehouse.
`scripts/publish_reports.py` reads dbt's `run_results.json`. Any model error, or any failed test tagged
`critical`, blocks publication, and the previous snapshot stays live. A successful publication is
recorded in `finance_audit.audit_report_publications` with a fingerprint of key figures. The copy is
atomic (write to a temporary file, then rename).

## Consequences
* A WARN (for example the planted AR difference) does not block publication but is visible on the
  dashboard. `--block-on-exceptions` makes open critical business exceptions block as well.
* Reports are reproducible. The fingerprint ties a screenshot or an export to one build.
