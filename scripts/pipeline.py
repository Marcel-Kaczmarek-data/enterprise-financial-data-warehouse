"""Cross-platform task runner (Windows, macOS, Linux). The Makefile delegates to this script.

    python scripts/pipeline.py <command> [options]

Commands
  setup          install Python dependencies into the active environment
  up / down      start / stop the core Docker services (PostgreSQL source, S3 object store)
  seed           generate the deterministic dataset and publish all source systems as of --cutoff
  advance        advance every source system to --to (incremental changes, late arrivals)
  ingest         extract ERP (PostgreSQL), CRM (REST API) and files into the S3 landing zone
  load           load committed landing batches into the local DuckDB raw layer
  transform      dbt seed + dbt build (models, snapshots and tests)
  publish        publication gate: publish the reporting snapshot only if critical checks pass
  dashboard      start the Streamlit dashboard on the published snapshot
  test           pytest unit + financial tests
  lint           ruff + sqlfluff
  docs           dbt docs generate
  demo           up -> seed -> ingest -> load -> transform -> publish (full local demonstration)
  incremental    advance -> ingest -> load -> transform -> publish (second, incremental run)
  reset          DESTRUCTIVE: delete pipeline state (asks for confirmation; --yes to skip)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
DBT_DIR = ROOT / "dbt_finance"
DEFAULT_CUTOFF = "2025-11-30T23:59:59+00:00"
DEFAULT_ADVANCE = "2025-12-31T23:59:59+00:00"


def run(cmd: list[str], cwd: Path = ROOT, env: dict | None = None, check: bool = True) -> int:
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    t0 = time.perf_counter()
    rc = subprocess.call(cmd, cwd=cwd, env={**os.environ, **(env or {})})
    print(f"<<< exit {rc} in {time.perf_counter() - t0:.1f}s", flush=True)
    if check and rc != 0:
        raise SystemExit(rc)
    return rc


def dbt(*args: str, check: bool = True) -> int:
    exe = Path(PY).with_name("dbt.exe" if os.name == "nt" else "dbt")
    return run([str(exe), *args], cwd=DBT_DIR, env={"DBT_PROFILES_DIR": str(DBT_DIR)}, check=check)


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def ensure_crm_api() -> subprocess.Popen | None:
    if port_open(8085):
        return None
    proc = subprocess.Popen(
        [PY, "-m", "source_systems.crm.api", "--port", "8085"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        if port_open(8085):
            return proc
        time.sleep(0.25)
    raise SystemExit("CRM API failed to start on :8085")


def wait_for_services() -> None:
    for _ in range(60):
        out = subprocess.run(
            ["docker", "compose", "ps", "--format", "{{.Name}}={{.Health}}"], cwd=ROOT, capture_output=True, text=True
        ).stdout
        if out and "starting" not in out and "unhealthy" not in out and out.count("healthy") >= 2:
            print(out.strip())
            return
        time.sleep(3)
    raise SystemExit("Docker services did not become healthy")


def cmd_up(_: argparse.Namespace) -> None:
    run(["docker", "compose", "up", "-d", "source-postgres", "object-store"])
    wait_for_services()


def cmd_down(_: argparse.Namespace) -> None:
    run(["docker", "compose", "down"])


def cmd_seed(a: argparse.Namespace) -> None:
    run([PY, "-m", "data_generator.main", "--profile", a.profile])
    run([PY, "scripts/export_seeds.py"])
    run([PY, "-m", "source_systems.erp.seed", "init", "--profile", a.profile, "--cutoff", a.cutoff])
    run(
        [PY, "-m", "source_systems.publish_files", "--profile", a.profile, "--cutoff", a.cutoff]
        + (["--inject-failures"] if a.inject_failures else [])
    )


def cmd_advance(a: argparse.Namespace) -> None:
    run([PY, "-m", "source_systems.erp.seed", "advance", "--to", a.to])
    run(
        [PY, "-m", "source_systems.publish_files", "--cutoff", a.to]
        + (["--inject-failures"] if a.inject_failures else [])
    )


def cmd_ingest(_: argparse.Namespace) -> None:
    proc = ensure_crm_api()
    try:
        run([PY, "-m", "ingestion.run"])
    finally:
        if proc:
            proc.terminate()


def cmd_load(_: argparse.Namespace) -> None:
    run([PY, "-m", "warehouse.local.load_raw"])


def cmd_transform(a: argparse.Namespace) -> None:
    dbt("seed", "--quiet")
    # snapshots run inside `dbt build` in DAG order (after the staging models they select from)
    dbt("build", *(["--full-refresh"] if a.full_refresh else []))


def cmd_publish(_: argparse.Namespace) -> None:
    run([PY, "scripts/publish_reports.py"])


def cmd_dashboard(_: argparse.Namespace) -> None:
    run([PY, "-m", "streamlit", "run", "dashboards/streamlit/app.py", "--server.headless=true"])


def cmd_test(_: argparse.Namespace) -> None:
    run([PY, "-m", "pytest", "tests", "-q", "-rs"])  # warehouse-backed suites skip (reported) if not built


def cmd_lint(_: argparse.Namespace) -> None:
    run([PY, "-m", "ruff", "check", "."], check=False)
    run([PY, "-m", "sqlfluff", "lint", "sql"], check=False)


def cmd_docs(_: argparse.Namespace) -> None:
    dbt("docs", "generate")


def cmd_demo(a: argparse.Namespace) -> None:
    timings: dict[str, float] = {}
    for name, fn in [
        ("up", cmd_up),
        ("seed", cmd_seed),
        ("ingest", cmd_ingest),
        ("load", cmd_load),
        ("transform", cmd_transform),
        ("publish", cmd_publish),
    ]:
        t0 = time.perf_counter()
        fn(a)
        timings[name] = round(time.perf_counter() - t0, 1)
    print("\nDemo pipeline timings (s):", json.dumps(timings))
    print("Start the dashboard with: python scripts/pipeline.py dashboard")


def cmd_incremental(a: argparse.Namespace) -> None:
    timings: dict[str, float] = {}
    for name, fn in [
        ("advance", cmd_advance),
        ("ingest", cmd_ingest),
        ("load", cmd_load),
        ("transform", cmd_transform),
        ("publish", cmd_publish),
    ]:
        t0 = time.perf_counter()
        fn(a)
        timings[name] = round(time.perf_counter() - t0, 1)
    print("\nIncremental run timings (s):", json.dumps(timings))


def cmd_reset(a: argparse.Namespace) -> None:
    run([PY, "scripts/reset_local.py"] + (["--yes"] if a.yes else []) + (["--sources"] if a.sources else []))


def cmd_setup(_: argparse.Namespace) -> None:
    run([PY, "-m", "pip", "install", "-r", "requirements.txt"])


COMMANDS = {
    "setup": cmd_setup,
    "up": cmd_up,
    "down": cmd_down,
    "seed": cmd_seed,
    "advance": cmd_advance,
    "ingest": cmd_ingest,
    "load": cmd_load,
    "transform": cmd_transform,
    "publish": cmd_publish,
    "dashboard": cmd_dashboard,
    "test": cmd_test,
    "lint": cmd_lint,
    "docs": cmd_docs,
    "demo": cmd_demo,
    "incremental": cmd_incremental,
    "reset": cmd_reset,
}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("--profile", default="development")
    p.add_argument("--cutoff", default=DEFAULT_CUTOFF)
    p.add_argument("--to", default=DEFAULT_ADVANCE)
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--inject-failures", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--sources", action="store_true")
    a = p.parse_args()
    COMMANDS[a.command](a)


if __name__ == "__main__":
    main()
