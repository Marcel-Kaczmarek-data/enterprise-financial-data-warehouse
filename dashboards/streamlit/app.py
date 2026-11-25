"""Halcyon Group - CFO Financial Analytics (Streamlit).

    streamlit run dashboards/streamlit/app.py

Reads only the published, validated warehouse snapshot (see lib/data.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.data import require_snapshot

st.set_page_config(
    page_title="Finance Intelligence · Halcyon Group", page_icon="📊", layout="wide", initial_sidebar_state="expanded"
)
st.markdown(
    """
<style>
  .block-container {padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px;}
  [data-testid="stSidebar"] {background: #f7f8fa; border-right: 1px solid #e9e9e9;}
  [data-testid="stSidebarNav"] span {font-size: 0.92rem;}
  h2 {font-weight: 650; letter-spacing: -0.01em;}
  div[data-testid="stExpander"] details {border: 1px solid #e9e9e9; border-radius: 10px;}
</style>""",
    unsafe_allow_html=True,
)

st.sidebar.markdown(
    "<div style='font-size:1.15rem;font-weight:700;color:#191919'>Finance Intelligence</div>"
    "<div style='color:#666;font-size:0.82rem;margin-bottom:6px'>Enterprise Financial Data Warehouse</div>",
    unsafe_allow_html=True,
)
require_snapshot()

P = Path(__file__).resolve().parent / "pages"
pages = {
    "Executive": [
        st.Page(P / "01_executive_overview.py", title="CFO Executive Overview", icon="🏛️", default=True),
    ],
    "Financial statements": [
        st.Page(P / "02_profit_and_loss.py", title="Profit and Loss", icon="📈"),
        st.Page(P / "03_balance_sheet.py", title="Balance Sheet", icon="⚖️"),
        st.Page(P / "04_cash_flow_treasury.py", title="Cash Flow & Treasury", icon="💶"),
    ],
    "Performance": [
        st.Page(P / "05_budget_vs_actual.py", title="Budget vs Actual", icon="🎯"),
        st.Page(P / "08_revenue_profitability.py", title="Revenue & Profitability", icon="🌍"),
        st.Page(P / "09_cost_centers.py", title="Cost Centers & Departments", icon="🏢"),
    ],
    "Working capital": [
        st.Page(P / "06_accounts_receivable.py", title="Accounts Receivable", icon="📥"),
        st.Page(P / "07_accounts_payable.py", title="Accounts Payable", icon="📤"),
    ],
    "Group & control": [
        st.Page(P / "10_consolidation.py", title="Financial Consolidation", icon="🔗"),
        st.Page(P / "11_reconciliation.py", title="Financial Reconciliation", icon="🧾"),
        st.Page(P / "12_financial_close.py", title="Financial Close", icon="🗓️"),
        st.Page(P / "13_data_quality.py", title="Data Quality & Pipeline", icon="🩺"),
    ],
}
st.navigation(pages).run()
