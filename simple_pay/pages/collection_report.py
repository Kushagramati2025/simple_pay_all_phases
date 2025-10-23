import streamlit as st
from streamlit_echarts import st_echarts
from reports_dashboards.collection import (
    set_custom_style,
    month_year_selector_flat,
    add_top_right_close_button,
    monthly_kpi_dashboard,
    chart_cashflow_bridge_horizontal,
    chart_income_composition_donut,
    show_download_dashboard_button,
    build_branch_leaderboard_options,
    # engine,  # not needed here
)

# ---------- Page + Theme ----------
st.set_page_config(layout="wide")
set_custom_style()

# ---------- Month/Year selector ----------
start_date, end_date, ok = month_year_selector_flat(form_key="month_year_flat__page")

if ok and start_date:
    y, m = start_date.year, start_date.month

    # KPIs (no header)
    monthly_kpi_dashboard(y, m, show_header=False)

    # Cash Flow Bridge + Income Donut
    c1, c2 = st.columns([1.4, 0.6])
    with c1:
        chart_cashflow_bridge_horizontal(y, m)
    with c2:
        st.markdown("<div style='height:60px;'></div>", unsafe_allow_html=True)
        chart_income_composition_donut(y, m)

    st.markdown("<br>", unsafe_allow_html=True)

    # ---- Branch Leaderboard (Receivable, Top & Bottom 10) ----
    opt_top, opt_bot, df_export = build_branch_leaderboard_options(
        y, m,
        metric="receivable",      # or "efficiency", "receipts", etc.
        top_n=10,
        min_receivable=0.0,       # filter branches with tiny receivable
        highlight_branch=None,    # e.g. "Chennai"
        titles=None,              # or custom ("Top — Receivable (₹)", "Bottom — Receivable (₹)")
        palette=None
    )

    if opt_top is None:
        st.info("No branch data for that month.")
    else:
        pslug = "collections"  # unique slug to avoid key clashes across pages
        lc1, lc2 = st.columns(2)
        with lc1:
            st_echarts(opt_top, height="420px", key=f"{pslug}_br_top_{y}_{m}_recv")
        with lc2:
            st_echarts(opt_bot, height="420px", key=f"{pslug}_br_bot_{y}_{m}_recv")

    show_download_dashboard_button()

else:
    st.info("Pick Month & Year and click **Show**.")
