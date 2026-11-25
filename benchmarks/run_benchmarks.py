"""Measure local performance on this machine. Nothing here is estimated: every figure is timed.

    python benchmarks/run_benchmarks.py [--profile small] [--skip-generator]

1. Generator throughput for a profile (writes to a temporary directory, so it does not touch pipeline state).
2. Timings of the most recent `dbt build` (dbt_finance/target/run_results.json): total and slowest nodes.

Results go to benchmarks/runs/<timestamp>.json (git-ignored) together with machine details.
Cloud (Snowflake) performance and cost are NOT measured here.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def bench_generator(profile: str) -> dict:
    from data_generator.main import generate

    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.perf_counter()
        manifest = generate(profile, Path(tmp) / profile)
        seconds = time.perf_counter() - t0
    return {
        "profile": profile,
        "seconds": round(seconds, 2),
        "journal_lines": manifest["journal_lines"],
        "journal_lines_per_second": round(manifest["journal_lines"] / seconds),
    }


def bench_dbt() -> dict | None:
    path = ROOT / "dbt_finance" / "target" / "run_results.json"
    if not path.exists():
        return None
    results = json.loads(path.read_text(encoding="utf-8"))
    nodes = sorted(results["results"], key=lambda r: r["execution_time"], reverse=True)
    return {
        "invocation_id": results["metadata"]["invocation_id"],
        "command": results["args"].get("which"),
        "elapsed_seconds": round(results["elapsed_time"], 1),
        "nodes": len(nodes),
        "slowest": [{"node": r["unique_id"], "seconds": round(r["execution_time"], 2)} for r in nodes[:10]],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="small")
    ap.add_argument("--skip-generator", action="store_true")
    a = ap.parse_args()
    report = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": {
            "python": platform.python_version(),
            "system": platform.platform(),
            "processor": platform.processor(),
        },
        "generator": None if a.skip_generator else bench_generator(a.profile),
        "dbt_last_build": bench_dbt(),
    }
    out = ROOT / "benchmarks" / "runs"
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{datetime.now(UTC):%Y%m%dT%H%M%S}.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"saved {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
