"""Shared UI: theme constants (validated reference palette), formatting, filters, KPI tiles, exports."""

from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from lib.data import meta, q

# Validated categorical order (dataviz reference palette, light surface). Fixed order, never cycled.
SERIES = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"]
NEUTRAL = "#b4b4b4"
# Status palette - reserved, always paired with an icon + label.
STATUS = {"good": "#0aac23", "warning": "#fbb315", "serious": "#f18a59", "critical": "#dc3c3d"}
STATUS_ICON = {"good": "✅", "warning": "⚠️", "serious": "🟠", "critical": "⛔"}
TEXT, TEXT_2, GRID, SURFACE = "#191919", "#666666", "#e9e9e9", "#ffffff"
# Diverging (favourable / unfavourable) uses two categorical poles with a neutral midpoint.
FAVOURABLE, UNFAVOURABLE = "#257de0", "#f47230"

SYMBOL = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "JPY": "¥",
    "INR": "₹",
    "CHF": "CHF ",
    "SEK": "SEK ",
    "CAD": "C$",
    "SGD": "S$",
    "CNY": "¥",
}


def money(value, currency: str = "EUR", decimals: int = 1, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "–"
    v = float(value)
    sym = SYMBOL.get(currency, currency + " ")
    sign = "-" if v < 0 else ("+" if signed and v > 0 else "")
    a = abs(v)
    if a >= 1e9:
        s = f"{a / 1e9:.{decimals}f}B"
    elif a >= 1e6:
        s = f"{a / 1e6:.{decimals}f}M"
    elif a >= 1e3:
        s = f"{a / 1e3:.{decimals}f}K"
    else:
        s = f"{a:,.0f}"
    return f"{sign}{sym}{s}"


def pct(value, decimals: int = 1, signed: bool = False) -> str:
    if value is None or pd.isna(value):
        return "–"
    return f"{float(value) * 100:{'+' if signed else ''}.{decimals}f}%"


def chart_layout(
    fig: go.Figure, title: str | None = None, height: int = 340, y_money: bool = True, legend: bool = True
) -> go.Figure:
    fig.update_layout(
        # Title sits in the top margin and the legend in its own row between title and plot (no overlap).
        template="none",
        height=height,
        margin={"l": 8, "r": 8, "t": (80 if legend else 44) if title else (36 if legend else 12), "b": 8},
        title={
            "text": title,
            "font": {"size": 15, "color": TEXT},
            "x": 0,
            "xanchor": "left",
            "yref": "container",
            "y": 1.0,
            "yanchor": "top",
            "pad": {"t": 10},
        }
        if title
        else None,
        font={"family": "Inter, Segoe UI, Helvetica, Arial, sans-serif", "size": 12, "color": TEXT_2},
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        hovermode="x unified",
        showlegend=legend,
        legend={"orientation": "h", "y": 1.02, "yanchor": "bottom", "x": 0, "font": {"color": TEXT}},
        hoverlabel={"bgcolor": "white", "font": {"color": TEXT}},
        bargap=0.25,
        bargroupgap=0.08,
    )
    fig.update_xaxes(showgrid=False, linecolor=GRID, tickfont={"color": TEXT_2})
    fig.update_yaxes(
        gridcolor=GRID,
        zeroline=True,
        zerolinecolor="#cfcfcf",
        tickfont={"color": TEXT_2},
        tickprefix="€" if y_money else None,
        tickformat="~s" if y_money else None,
    )
    fig.update_traces(marker_line_color=SURFACE, marker_line_width=2, selector={"type": "bar"})
    return fig


@dataclass
class Filters:
    fiscal_year: int
    fiscal_period: str
    scope: str  # CONSOLIDATED or STANDALONE
    entity_id: str  # GROUP or Exx
    entity_label: str
    compare: str  # "Prior year" | "Budget"
    periods_in_year: list[str]


def sidebar_filters(show_scope: bool = True) -> Filters:
    entities = q(
        "select entity_id, entity_name, country_name, functional_currency from finance_core.dim_legal_entity order by entity_id"
    )
    periods = q("select distinct fiscal_period from finance_marts.mart_profit_and_loss order by 1")[
        "fiscal_period"
    ].tolist()
    years = sorted({int(p[:4]) for p in periods})
    st.sidebar.markdown("### Filters")
    year = st.sidebar.selectbox("Fiscal year", years, index=len(years) - 1, key="f_year")
    year_periods = [p for p in periods if int(p[:4]) == year]
    period = st.sidebar.selectbox(
        "Fiscal period (month end)", year_periods, index=len(year_periods) - 1, key="f_period"
    )
    if show_scope:
        options = ["GROUP", *entities["entity_id"].tolist()]
        labels = {"GROUP": "Group (consolidated)"} | {
            r.entity_id: f"{r.entity_id} · {r.entity_name}" for r in entities.itertuples()
        }
        entity = st.sidebar.selectbox("Reporting entity", options, format_func=labels.get, key="f_entity")
    else:
        entity, labels = "GROUP", {"GROUP": "Group (consolidated)"}
    compare = st.sidebar.radio("Comparison", ["Prior year", "Budget"], horizontal=True, key="f_compare")
    _freshness()
    return Filters(
        year,
        period,
        "CONSOLIDATED" if entity == "GROUP" else "STANDALONE",
        entity,
        labels[entity],
        compare,
        year_periods[: year_periods.index(period) + 1],
    )


def _freshness() -> None:
    m = meta()
    st.sidebar.markdown("---")
    pub = m["publication"]
    if pub:
        st.sidebar.caption(
            f"**Data through:** {m['latest_posting_date']}  \n"
            f"**Published:** {pd.Timestamp(pub[1]).strftime('%Y-%m-%d %H:%M')} UTC  \n"
            f"**Version:** `{pub[0]}`  \n**Fingerprint:** `{pub[2]}`"
        )
    st.sidebar.caption("Synthetic data · Halcyon Group (fictitious) · amounts in EUR unless stated")


def page_header(title: str, subtitle: str, f: Filters | None = None) -> None:
    st.markdown(f"<h2 style='margin-bottom:0'>{title}</h2>", unsafe_allow_html=True)
    ctx = f" · {f.entity_label} · {f.fiscal_period}" if f else ""
    st.markdown(f"<div style='color:{TEXT_2};margin-bottom:12px'>{subtitle}{ctx}</div>", unsafe_allow_html=True)


def kpi(
    col, label: str, value: str, delta: str | None = None, help_text: str | None = None, delta_good: bool | None = None
) -> None:
    color = TEXT_2 if delta_good is None else (STATUS["good"] if delta_good else STATUS["critical"])
    arrow = "" if delta_good is None else ("▲ " if delta_good else "▼ ")
    delta_html = f"<div style='color:{color};font-size:0.85rem'>{arrow}{delta}</div>" if delta else ""
    col.markdown(
        f"""<div style="border:1px solid {GRID};border-radius:10px;padding:14px 16px;background:{SURFACE};"
             title="{help_text or ""}">
              <div style="color:{TEXT_2};font-size:0.8rem;text-transform:uppercase;letter-spacing:.04em">{label}</div>
              <div style="color:{TEXT};font-size:1.55rem;font-weight:650;line-height:1.3">{value}</div>{delta_html}
            </div>""",
        unsafe_allow_html=True,
    )


def status_badge(state: str, label: str) -> str:
    return (
        f"<span style='border:1px solid {STATUS[state]};border-radius:12px;padding:2px 10px;"
        f"font-size:0.8rem;color:{TEXT}'>{STATUS_ICON[state]} {label}</span>"
    )


def table_with_export(
    df: pd.DataFrame, name: str, height: int = 380, search: bool = True, column_config: dict | None = None
) -> None:
    view = df
    if search and len(df):
        term = st.text_input("Search", key=f"search_{name}", placeholder="Filter rows containing…")
        if term:
            mask = df.astype(str).apply(lambda c: c.str.contains(term, case=False, na=False)).any(axis=1)
            view = df[mask]
    st.dataframe(view, use_container_width=True, height=height, hide_index=True, column_config=column_config)
    c1, c2, _ = st.columns([1, 1, 6])
    c1.download_button("⬇ CSV", view.to_csv(index=False).encode(), f"{name}.csv", "text/csv", key=f"csv_{name}")
    # Excel has no timezone type: export tz-aware timestamps as naive UTC (the CSV keeps the offset).
    excel = view.copy()
    for col in excel.columns:
        if isinstance(excel[col].dtype, pd.DatetimeTZDtype):
            excel[col] = excel[col].dt.tz_convert("UTC").dt.tz_localize(None)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        excel.to_excel(xw, index=False, sheet_name=name[:31])
    c2.download_button(
        "⬇ Excel",
        buf.getvalue(),
        f"{name}.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"xlsx_{name}",
    )


def money_columns(cols: list[str], currency: str = "EUR") -> dict:
    sym = SYMBOL.get(currency, "")
    return {c: st.column_config.NumberColumn(c, format=f"{sym}%,.0f") for c in cols}
