"""Capture real screenshots of every dashboard page (Playwright + a locally installed Chrome).

    streamlit run dashboards/streamlit/app.py --server.port 8501      (in another terminal)
    python scripts/capture_screenshots.py [--base-url http://127.0.0.1:8501] [--browser-channel chrome]

Fails (exit 1) if any page renders a Streamlit exception, so it doubles as a dashboard smoke test.
Requires `pip install playwright` (dev only, not in requirements.txt). With --browser-channel ""
Playwright's bundled Chromium is used instead (`playwright install chromium`).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboards" / "screenshots"

PAGES = [
    ("", "01_executive_overview"),
    ("profit_and_loss", "02_profit_and_loss"),
    ("balance_sheet", "03_balance_sheet"),
    ("cash_flow_treasury", "04_cash_flow_treasury"),
    ("budget_vs_actual", "05_budget_vs_actual"),
    ("accounts_receivable", "06_accounts_receivable"),
    ("accounts_payable", "07_accounts_payable"),
    ("revenue_profitability", "08_revenue_profitability"),
    ("cost_centers", "09_cost_centers"),
    ("consolidation", "10_consolidation"),
    ("reconciliation", "11_reconciliation"),
    ("financial_close", "12_financial_close"),
    ("data_quality", "13_data_quality"),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8501")
    ap.add_argument("--browser-channel", default="chrome")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--only", nargs="*", help="subset of output names")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=a.browser_channel or None, args=["--no-proxy-server"])
        page = browser.new_page(viewport={"width": a.width, "height": 1000}, device_scale_factor=1)
        for path, name in PAGES:
            if a.only and name not in a.only:
                continue
            page.goto(f"{a.base_url}/{path}", wait_until="networkidle")
            # Streamlit renders asynchronously: wait for the app to report it is idle and charts are drawn.
            page.wait_for_selector("[data-testid='stMain']", timeout=60_000)
            page.wait_for_function("() => !document.querySelector('[data-testid=\"stStatusWidget\"]')", timeout=120_000)
            page.wait_for_timeout(2500)
            errors = page.locator("[data-testid='stException']")
            if errors.count():
                failures.append(f"{name}: {errors.first.inner_text()[:600]}")
            height = page.evaluate("() => document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
            page.set_viewport_size({"width": a.width, "height": min(max(int(height), 1000), 6000)})
            page.wait_for_timeout(1200)
            target = OUT / f"{name}.png"
            page.screenshot(path=str(target), full_page=False)
            page.set_viewport_size({"width": a.width, "height": 1000})
            print(f"{'ERROR' if errors.count() else 'ok   '} {name} -> {target.relative_to(ROOT)}")
        browser.close()
    for f in failures:
        print(f"\nPAGE EXCEPTION {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
