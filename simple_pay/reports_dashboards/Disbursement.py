import streamlit as st
import pandas as pd
import numpy as np
import seaborn as sns
import plotly.express as px
import matplotlib.pyplot as plt   # for Matplotlib charts
import plotly.express as px 

from streamlit_echarts import st_echarts

from simple_pay.service.helper import get_selected_currency_code, get_selected_currency_name

# NEW — adjust module paths if yours differ
from tools.config_paths import PARQUET_ROOT   # provides your parquet root folder
from Calculation.loan_duckdb import (
    compute_all_38_duckdb, load_config, LoanCalcConfig
)


import io, base64
import pdfkit
import pandas as pd
import numpy as np
import matplotlib.pyplot as _plt
import shutil


from streamlit_echarts import st_echarts

from simple_pay.service.helper import get_selected_currency_code, get_selected_currency_name

CURRENCY_CODE = st.session_state.get("currency_code") or get_selected_currency_code()
CURRENCY_NAME = st.session_state.get("currency_name") or get_selected_currency_name() or "—"

st.caption(f"Currency: **{CURRENCY_NAME}** [{CURRENCY_CODE or '—'}]")

# Fallbacks (delete if you already have these in your app)
THEME_PALETTE = {
    "brand":   "#1f6feb",
    "brand2":  "#0ea5e9",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger":  "#ef4444",
    "indigo":  "#7c3aed",
    "title":   "#6b7280",
    "value":   "#0f172a",
    "muted":   "#94a3b8",
}
def _fmt_inr(x: float) -> str:
    # Simple Indian grouping formatter (₹ 12,34,56,789.00). Replace with your own if you already have it.
    try:
        import math
        neg = x < 0
        x = abs(float(x))
        s = f"{x:,.2f}"
        i, d = s.split(".")
        if len(i) <= 3:
            out = i
        else:
            out = i[-3:]
            i = i[:-3]
            while len(i) > 2:
                out = i[-2:] + "," + out
                i = i[:-2]
            if i:
                out = i + "," + out
        return f"{'-' if neg else ''}{out}.{d}"
    except Exception:
        return f"{x:,.2f}"

def plot_status_pie_echarts(active_count: int, closed_count: int):
    total = int((active_count or 0) + (closed_count or 0))
    active_pct = (active_count / total * 100.0) if total else 0.0

    center_amount_text = f"Total {total:,}"
    center_paid_text   = f"Active {active_pct:.1f}%"

    data_points = [
        {"name": "Active", "value": [active_count, f"{active_count:,}"]},
        {"name": "Closed", "value": [closed_count, f"{closed_count:,}"]},
    ]

    options = {
        "color": [THEME_PALETTE["brand"], THEME_PALETTE["indigo"]],
        "animationDuration": 800,
        "animationEasing": "cubicOut",
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}<br/>Count: {@[1]}<br/>{d}%"
        },
        "legend": {
            "orient": "horizontal",
            "bottom": 0,
            "itemGap": 16,
            "textStyle": {"color": THEME_PALETTE["title"], "fontSize": 12}
        },
        "series": [{
            "name": "Loan Status",
            "type": "pie",
            "radius": ["45%", "70%"],
            "center": ["50%", "50%"],
            "avoidLabelOverlap": True,
            "stillShowZeroSum": True,
            "clockwise": True,
            "itemStyle": {
                "borderRadius": 8,
                "borderColor": "#ffffff",
                "borderWidth": 2
            },
            "label": {
                "show": True,
                "formatter": "{b}\n{@[1]} ({d}%)",
                "fontSize": 15,
                "lineHeight": 16,
                "color": THEME_PALETTE["value"]
            },
            "emphasis": {
                "scale": True,
                "scaleSize": 3,
                "itemStyle": {"shadowBlur": 12, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.25)"}
            },
            "data": data_points
        }],
        "graphic": [{
            "type": "group",
            "left": "center",
            "top": "45%",
            "z": 100,
            "children": [
                {
                    "type": "text",
                    "style": {
                        "text": center_amount_text,
                        "textAlign": "center",
                        "fontSize": 14,
                        "fontWeight": 700,
                        "fill": THEME_PALETTE["value"]
                    }
                },
                {
                    "type": "text",
                    "top": 18,
                    "style": {
                        "text": center_paid_text,
                        "textAlign": "center",
                        "fontSize": 11,
                        "fill": THEME_PALETTE["muted"]
                    }
                }
            ]
        }]
    }
    st.subheader("Active vs Closed Loans")
    st_echarts(options=options, height="360px", key="status_ring_pie")


def plot_advanced_pie_echarts(amount_disbursed: float,
                              amount_principal_paid: float,
                              amount_interest_paid: float,
                              grand_total: float,
                              grand_total_paid_pct: float):

    # Coerce & clamp
    amount_disbursed      = float(max(0.0, amount_disbursed or 0.0))
    amount_principal_paid = float(max(0.0, amount_principal_paid or 0.0))
    amount_interest_paid  = float(max(0.0, amount_interest_paid or 0.0))
    grand_total           = float(max(0.0, grand_total or 0.0))
    grand_total_paid_pct  = float(max(0.0, grand_total_paid_pct or 0.0))

    center_amount_text = f"₹ {_fmt_inr(grand_total)}"
    center_paid_text   = f"Paid {grand_total_paid_pct:.1f}%"

    data_points = [
        {"name": "Disbursed",      "value": [amount_disbursed,      f"₹ {_fmt_inr(amount_disbursed)}"]},
        {"name": "Principal Paid", "value": [amount_principal_paid, f"₹ {_fmt_inr(amount_principal_paid)}"]},
        {"name": "Interest Paid",  "value": [amount_interest_paid,  f"₹ {_fmt_inr(amount_interest_paid)}"]},
    ]

    options = {
        # Apply your brand colors to slices (order matches data_points above)
        "color": [THEME_PALETTE["brand"], THEME_PALETTE["success"], THEME_PALETTE["warning"]],
        "animationDuration": 800,
        "animationEasing": "cubicOut",
        "tooltip": {
            "trigger": "item",
            "formatter": "{b}<br/>{@[1]}<br/>{d}%"
        },
        "legend": {
            "orient": "horizontal",
            "bottom": 0,
            "itemGap": 16,
            "textStyle": {"color": THEME_PALETTE["title"], "fontSize": 12}
        },
        "series": [{
            "name": "Amounts",
            "type": "pie",
            "radius": ["45%", "70%"],
            "center": ["50%", "50%"],
            "avoidLabelOverlap": True,
            "stillShowZeroSum": True,
            "clockwise": True,
            "itemStyle": {
                "borderRadius": 8,
                "borderColor": "#ffffff",
                "borderWidth": 2
            },
            "label": {
                "show": True,
                "formatter": "{b}\n{@[1]} ({d}%)",
                "fontSize": 15,
                "lineHeight": 16,
                "color": THEME_PALETTE["value"]
            },
            "emphasis": {
                "scale": True,
                "scaleSize": 3,
                "itemStyle": {"shadowBlur": 12, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.25)"}
            },
            "data": data_points
        }],
        "graphic": [{
            "type": "group",
            "left": "center",
            "top": "45%",
            "z": 100,
            "children": [
                {
                    "type": "text",
                    "style": {
                        "text": center_amount_text,
                        "textAlign": "center",
                        "fontSize": 14,
                        "fontWeight": 700,
                        "fill": THEME_PALETTE["value"]
                    }
                },
                {
                    "type": "text",
                    "top": 18,
                    "style": {
                        "text": center_paid_text,
                        "textAlign": "center",
                        "fontSize": 11,
                        "fill": THEME_PALETTE["muted"]
                    }
                }
            ]
        }]
    }

    st_echarts(options=options, height="360px", key="advanced_ring_pie")


# --------------------------- Custom CSS ---------------------------
def set_custom_style():
    st.markdown("""
        <style>
            .main { background-color: #f4f7fa; padding: 2rem; }
            .report-title {
                font-size: 30px; font-weight: 800; color: #2c3e50;
                margin-bottom: 1.5rem; border-left: 6px solid #3498db; padding-left: 15px;
            }
            .range-message { font-size: 17px; color: #555; margin-bottom: 1.5rem; }
            .stDateInput > label { font-size: 16px; font-weight: 600; color: #2c3e50; }
            .stDataFrame {
                border-radius: 12px !important; border: 1px solid #d0d0d0 !important;
                margin-bottom: 2rem; box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }
            div[data-testid="metric-container"] {
                background: #ffffff; padding: 15px; border-radius: 10px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); margin-top: 0.5rem; margin-bottom: 1rem;
            }
            .total-box {
                font-size: 20px; font-weight: bold; color: #1e8449; background-color: #d4efdf;
                padding: 15px 20px; border-radius: 10px; width: fit-content;
                box-shadow: 0px 4px 10px rgba(0,0,0,0.1); margin-top: 1.5rem; margin-bottom: 2rem;
                transition: transform 0.2s;
            }
            .total-box:hover { transform: scale(1.02); }
        </style>
    """, unsafe_allow_html=True)
    
from pyppeteer import launch
async def capture_page():
            browser = await launch()
            page = await browser.newPage()
            # Point to your Streamlit page running locally
            await page.goto("http://localhost:8501/Reports", {"waitUntil": "networkidle0"})
            
            pdf_bytes = await page.pdf()
            screenshot_bytes = await page.screenshot()
            
            await browser.close()
            return pdf_bytes, screenshot_bytes
        
def _fetch_scalar_sum(sql: str, params: tuple | list | None = None) -> float:
    from simple_pay.utils.database_connection import DatabaseConnection
    db = DatabaseConnection()
    cur = None
    try:
        db.connect()  # sets db.conn and db.cursor
        cur = db.cursor or (db.conn.cursor() if db.conn else None)
        if cur is None:
            raise RuntimeError("DatabaseConnection.connect() did not provide a cursor")
 
        cur.execute(sql, params or ())
        row = cur.fetchone()
        val = row[0] if row else 0
        return float(val or 0.0)
 
    except Exception as e:
        # show the real reason in the app so you can fix table/column names fast
        st.error(f"DB error for query:\n{sql}\n→ {e}")
        return 0.0
 
    finally:
        try:
            if cur and hasattr(cur, "close"):
                cur.close()
        except Exception:
            pass
        # closes cursor and connection safely
        db.close()
 
 
def get_total_membership_income() -> float:
    # Table/column from your DDL: members.membership_income DECIMAL(10,2)
    return _fetch_scalar_sum(
        "SELECT COALESCE(SUM(`membership_income`), 0) FROM `keny`.`members`;"
    )
 
 
def get_total_receipts_amount() -> float:
    # Table/column from your DDL: receipt.amount_received DECIMAL(10,2)
    # If your actual table is spelled `reciept`, change it below.
    return _fetch_scalar_sum(
        "SELECT COALESCE(SUM(`amount_received`), 0) FROM `keny`.`receipt`;"
        # "SELECT COALESCE(SUM(`amount_received`), 0) FROM `keny`.`reciept`;"
    )
 
 
total_membership_income = float(get_total_membership_income() or 0)
total_receipts_amount  = float(get_total_receipts_amount() or 0)       

# --------------------------- Graphs ---------------------------
def graph(filtered_df):
    # try:
    #     print(filtered_df.dtypes)
    #     if filtered_df.empty:
    #         st.warning("No data available to plot.")
    #         return

    #     # Use named columns that we produce in the main function
    #     daily_totals = (
    #         filtered_df.groupby("Date")[["Principal Paid", "Interest Paid"]]
    #         .sum().reset_index()
    #     )

    #     fig = px.bar(
    #         daily_totals,
    #         x="Date",
    #         y=["Principal Paid", "Interest Paid"],
    #         barmode="stack",
    #         color_discrete_sequence=["#3498db", "#e67e22"]
    #     )
    #     fig.update_layout(
    #         margin=dict(t=20, b=20, l=20, r=20),
    #         legend=dict(
    #             orientation="v",   # vertical
    #             y=0.5,
    #             yanchor="middle",
    #             x=1.05,
    #             xanchor="left"
    #         ),
    #         height=350,
    #     )

    #     fig.update_traces(
    #         hole=0.5,   # controls donut size
    #         textposition="inside"
    #     )



    #     amount_disbursed = filtered_df["Principal"].sum()
    #     amount_principal_paid = filtered_df["Principal Paid"].sum()
    #     amount_interest_paid = filtered_df["Interest Paid"].sum()

    #     pie_df = pd.DataFrame({
    #         "Category": ["Disbursed", "Principal Paid", "Interest Paid"],
    #         "Value": [amount_disbursed, amount_principal_paid, amount_interest_paid]
    #     })

    #     fig2 = px.pie(
    #         pie_df, values="Value", names="Category", hole=0.45,
    #         color_discrete_sequence=px.colors.qualitative.Set2
    #     )
    #     fig2.update_traces(textposition="inside", textinfo="percent+label")
    #     fig2.update_layout(margin=dict(t=40, b=40, l=40, r=40), title=None)

    #     col1, col2 = st.columns([1, 1])
    #     with col1:
    #         st.markdown("<h4 style='text-align:center; color:#1e3a8a;'>Daily Payments (Principal & Interest)</h4>", unsafe_allow_html=True)
    #         st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    #     with col2:
    #         st.markdown("<h4 style='text-align:center; color:#1e3a8a;'>Disbursed vs Repayments Breakdown</h4>", unsafe_allow_html=True)
    #         st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


    # except Exception as e:
    #     st.error(f"Error generating graphs: {str(e)}")
    
    filtered_df.index = filtered_df.index + 1
    st.dataframe(
        filtered_df[[
            "Date", "Loan ID", "Principal", "Interest Accrued",
            "Principal Paid", "Interest Paid", "Balance",
            "Paid after 30 days"
        ]],
        use_container_width=True,
        height=280
    )

#---------------------------------------------------------------------------------------------------


# Required imports (put near top of your file)
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import FuncFormatter

# # --- Helper: pretty short numbers (K, M) ---
def short_num(n):
    """Small helper to format large numbers (K/M/B) for legend text."""
    try:
        n = float(n)
    except Exception:
        return "0"
    if abs(n) >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if abs(n) >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n/1_000:.1f}K"
    if n.is_integer():
        return f"{int(n)}"
    return f"{n:.2f}"

# --- Main plotting function (Matplotlib + Seaborn) ---
def streamlit_daily_area_line_seaborn(
    filtered_df,
    value_col="Amount Paid",        # default = your new column
    repay_col="Pricipal Paid",      # default = your new column (typo handled below)
    default_window_days=30,
    max_ticks=9,
    *,
    dark=False,
    theme_colors=None,
    title=None,                     # optional custom title
    currency_code=None,             # optional "KES", "INR", etc. for title
):
    """
    Themed daily area + line chart for Streamlit that matches your card CSS.

    - filtered_df : dataframe with ['Date', value_col, repay_col]
    - dark        : set True if you're running dark palette (optional)
    - theme_colors: override palette (dict of hex/rgba strings) if needed
    - title       : set a custom plot title; defaults to "<value_col> vs <repay_col>"
    - currency_code : if given, will append " (<CODE>)" to the title
    """

    # --- local imports (keeps this function drop-in) ---
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns
    import streamlit as st
    from matplotlib.ticker import FuncFormatter

    # --- defaults matching your CSS variables ---
    default_light = dict(
        brand="#1f6feb",
        brand2="#0ea5e9",
        success="#10b981",
        warning="#f59e0b",
        danger="#ef4444",
        indigo="#7c3aed",
        surface="#ffffff",
        surface2="#fbfdff",
        border_rgba=(30/255, 65/255, 103/255, 0.08),  # rgba(30,65,103,0.08)
        title="#6b7280",
        value="#0f172a",
        grid_rgba=(0.4, 0.4, 0.4, 0.18),              # subtle dotted grid
    )
    default_dark = dict(
        brand="#1f6feb",
        brand2="#0ea5e9",
        success="#10b981",
        warning="#f59e0b",
        danger="#ef4444",
        indigo="#7c3aed",
        surface="#0b1220",
        surface2="#0f1626",
        border_rgba=(1, 1, 1, 0.08),
        title="#9aa4b2",
        value="#eef2ff",
        grid_rgba=(1, 1, 1, 0.22),
    )
    base = default_dark if dark else default_light
    C = {**base, **(theme_colors or {})}

    # --- helpers ---
    def short_num(v):
        try:
            v = float(v)
        except Exception:
            return "0"
        a = abs(v)
        if a >= 1_000_000_000: return f"{v/1_000_000_000:.1f}B"
        if a >= 1_000_000:     return f"{v/1_000_000:.1f}M"
        if a >= 1_000:         return f"{v/1_000:.1f}K"
        return f"{int(v)}"

    def pretty_name(name: str) -> str:
        # humanize + fix common typo
        s = str(name).replace("_", " ").strip().title()
        s = s.replace("Pricipal", "Principal")
        return s

    value_label = pretty_name(value_col)     # e.g., "Amount Paid"
    repay_label = pretty_name(repay_col)     # e.g., "Principal Paid"

    # --- validate input ---
    if filtered_df is None or len(filtered_df) == 0:
        st.warning("No data to plot.")
        return

    df = filtered_df.copy()
    # allow either 'Date' column or derive from 'Disbursement Date'
    if "Date" not in df.columns and "Disbursement Date" in df.columns:
        df["Date"] = df["Disbursement Date"]

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Date"])
    if df.empty:
        st.warning("No valid dates after parsing.")
        return

    for col in [value_col, repay_col]:
        if col not in df.columns:
            st.error(f"Missing required column: {col}")
            return

    # --- aggregate to daily & fill gaps ---
    daily = df.groupby("Date", as_index=True).agg({value_col: "sum", repay_col: "sum"})
    if daily.empty:
        st.warning("No daily rows after aggregation.")
        return

    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = (
        daily.reindex(full_idx, fill_value=0)
             .rename_axis("Date")
             .reset_index()
    )

    n = len(daily)
    plot_df = daily.tail(default_window_days).reset_index(drop=True) if n > default_window_days else daily.reset_index(drop=True)

    # --- seaborn + rc with your theme ---
    sns.set_style("whitegrid")
    plt.rcParams.update({
        "axes.titlesize": 15,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "legend.frameon": True,
        "legend.fontsize": 9,
        "figure.autolayout": True,
    })

    # --- figure / axes styled to match cards ---
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=110)

    # figure & axes background like your surfaces
    fig.patch.set_facecolor(C["surface"])
    ax.set_facecolor(C["surface2"])

    # spine + border tint
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color(C["border_rgba"])
        spine.set_linewidth(1)

    # --- plot ---
    x = np.arange(len(plot_df))
    disb_color = C["brand"]     # area + bars (Amount Paid)
    repay_color = C["danger"]   # repayment line (Principal Paid)
    trend_color = C["title"]    # soft neutral

    # filled area (Amount Paid)
    ax.fill_between(
        x, plot_df[value_col],
        step="mid", alpha=0.30,
        color=disb_color, label=value_label, zorder=2
    )
    # faint bars for depth
    ax.bar(x, plot_df[value_col], color=disb_color, alpha=0.14, width=0.9, zorder=1)

    # repayment line (Principal Paid)
    ax.plot(
        x, plot_df[repay_col],
        color=repay_color, marker="o", linewidth=2.2, markersize=5.5,
        label=repay_label, zorder=3
    )

    # trend line for Amount Paid
    if len(plot_df) > 1 and float(plot_df[value_col].sum()) > 0:
        coeff = np.polyfit(x, plot_df[value_col], 1)
        ax.plot(x, np.poly1d(coeff)(x), ls="--", color=trend_color, linewidth=1.3, label="Trend", zorder=2)

    # peak annotations on Amount Paid
    top_n = min(3, len(plot_df))
    for i in plot_df[value_col].nlargest(top_n).index.tolist():
        y = float(plot_df[value_col].iloc[i])
        if y > 0:
            ax.annotate(
                short_num(y),
                xy=(i, y), xytext=(0, 8), textcoords="offset points",
                ha="center", fontsize=9, color=C["brand"],
                weight="bold", zorder=5
            )

    # sparse labels on Principal Paid
    rep_max = float(plot_df[repay_col].max()) if len(plot_df) else 0
    denom = max(2, (max_ticks or 0))
    step = max(1, len(plot_df) // (denom - 1))
    y_pad = float(max(1e-9, plot_df[value_col].max())) * 0.02
    for i in range(0, len(plot_df), step):
        y = float(plot_df[repay_col].iloc[i])
        if y > 0 or y == rep_max:
            ax.text(i, y + y_pad, short_num(y), ha="center", va="bottom",
                    fontsize=8, color=repay_color)

    # titles/labels styled like your tokens
    final_title = title or f"{value_label} vs {repay_label}"
    if currency_code:
        final_title += f" ({currency_code})"
    ax.set_title(final_title, fontsize=16, weight="700", color=C["value"])
    ax.set_xlabel("Day", color=C["title"], labelpad=6)
    ax.set_ylabel("Amount", color=C["title"], labelpad=6)

    # xticks density + color
    n_plot = len(plot_df)
    safe_max_ticks = max(1, int(max_ticks) if isinstance(max_ticks, (int, float)) else 9)
    tick_step = max(1, n_plot // safe_max_ticks)
    tick_idx = list(range(0, n_plot, tick_step))
    tick_labels = [pd.to_datetime(plot_df["Date"]).dt.strftime("%d %b").iloc[i] for i in tick_idx]
    ax.set_xticks(tick_idx); ax.set_xticklabels(tick_labels, rotation=0, fontsize=9, color=C["title"])
    ax.tick_params(axis="y", labelsize=9, colors=C["title"])

    # y-format
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: short_num(v)))

    # grid (dotted) matching border tone
    ax.grid(axis="y", linestyle=(0, (2, 4)), linewidth=0.7, color=C["grid_rgba"], alpha=1.0)
    ax.set_axisbelow(True)

    # legend styled like card chip
    leg = ax.legend(loc="upper right")
    leg.get_frame().set_facecolor(C["surface"])
    leg.get_frame().set_edgecolor(C["border_rgba"])
    leg.get_frame().set_linewidth(1.0)
    for text in leg.get_texts():
        text.set_color(C["title"])

    plt.tight_layout()
    st.pyplot(fig, use_container_width=False)


from streamlit_echarts import st_echarts

# Centralized palette to match your CSS variables
THEME_PALETTE = {
    "brand":   "#1f6feb",
    "brand2":  "#0ea5e9",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger":  "#ef4444",
    "indigo":  "#7c3aed",
    "title":   "#6b7280",  # matches --title
    "value":   "#0f172a",  # matches --value
    "muted":   "#64748b",  # used for secondary text
}

def _fmt_inr(n: float) -> str:
    try:
        return f"{float(n):,.0f}"
    except Exception:
        return "0"




def _pick_settlement_col(df: pd.DataFrame) -> str | None:
    """Find a plausible settlement/closure date column if present."""
    candidates = [
        "settled_date", "closed_date", "closure_date",
        "balance_zero_date", "paid_off_date", "last_payment_date"
    ]
    for c in candidates:
        if c in df.columns:
            return c
    return None


def plot_donut_paid_interest_balance(principal_paid: float, interest_paid: float, balance: float):
    total = float(max(0.0, principal_paid) + max(0.0, interest_paid) + max(0.0, balance))
    paid_pct = (principal_paid + interest_paid) / total * 100 if total > 0 else 0.0

    options = {
        "color": [THEME_PALETTE["success"], THEME_PALETTE["warning"], THEME_PALETTE["indigo"]],
        "animationDuration": 800,
        "tooltip": {"trigger": "item", "formatter": "{b}<br/>{@[1]}<br/>{d}%"},
        "legend": {
            "orient": "horizontal", "bottom": 0, "itemGap": 16,
            "textStyle": {"color": THEME_PALETTE["title"], "fontSize": 12}
        },
        "series": [{
            "name": "Composition",
            "type": "pie",
            "radius": ["45%", "70%"],
            "center": ["50%", "50%"],
            "avoidLabelOverlap": True,
            "stillShowZeroSum": True,
            "clockwise": True,
            "itemStyle": {"borderRadius": 8, "borderColor": "#ffffff", "borderWidth": 2},
            "label": {
                "show": True,
                "formatter": "{b}\n{@[1]} ({d}%)",
                "fontSize": 15, "lineHeight": 16, "color": THEME_PALETTE["value"]
            },
            "data": [
                {"name": "Principal Paid", "value": [float(principal_paid), f"{principal_paid:,.2f}"]},
                {"name": "Interest Paid",  "value": [float(interest_paid),  f"{interest_paid:,.2f}"]},
                {"name": "Balance",        "value": [float(balance),        f"{balance:,.2f}"]},
            ]
        }],
        "graphic": [{
            "type": "group", "left": "center", "top": "45%", "z": 100,
            "children": [
                {"type": "text", "style": {
                    "text": f"Paid {paid_pct:.1f}%", "textAlign": "center",
                    "fontSize": 14, "fontWeight": 700, "fill": THEME_PALETTE["value"]
                }},
                {"type": "text", "top": 18, "style": {
                    "text": f"Total {total:,.2f}", "textAlign": "center",
                    "fontSize": 11, "fill": THEME_PALETTE["muted"]
                }},
            ]
        }]
    }
    st_echarts(options=options, height="360px", key="paid_interest_balance_pie")


# --------------------------- Main Function ---------------------------
def Disbursement():
    try:
        # ---------------- Date selection (no balance_view) ----------------
        # ---- Discover available data range from DuckDB (full scan, single call) ----
        probe = compute_all_38_duckdb(
            start_date="1900-01-01",
            end_date="2100-01-01",
            parquet_root=PARQUET_ROOT,
        )

        if probe is None or probe.empty:
            st.warning("No disbursement data available.")
            return pd.DataFrame(),None,None,None,None,None,None,None,None,None,None,None,None

        # map to actual columns in probe
        _probe_cols = {c.lower(): c for c in probe.columns}
        if "disb_date" not in _probe_cols:
            st.error("Calculator output missing 'disb_date' column.")
            return pd.DataFrame(),None,None,None,None,None,None,None,None,None,None,None,None

        _disb_col = _probe_cols["disb_date"]
        # normalize to date for picker bounds
        _data_min = pd.to_datetime(probe[_disb_col], errors="coerce").min()
        _data_max = pd.to_datetime(probe[_disb_col], errors="coerce").max()
        if pd.isna(_data_min) or pd.isna(_data_max):
            st.warning("No valid disbursement dates found.")
            return pd.DataFrame(),None,None,None,None,None,None,None,None,None,None,None,None

        data_min = _data_min.date()
        data_max = _data_max.date()


        st.markdown("""
            <style>
            div[data-testid="stForm"] {
                top: 500px; border: 2px solid #4CAF50; padding: 20px; border-radius: 12px;
                box-shadow: 0 4px 10px rgba(0,0,0,0.1); margin-top: 30px;
            }
            div[data-testid="stForm"] label { font-weight: bold; }
            div[data-testid="stForm"] button { border-radius: 8px !important; padding: 8px 16px !important; }
            </style>
        """, unsafe_allow_html=True)

        with st.form("disb_date_form", clear_on_submit=False):
            col1, col2, col3, col4, col5 = st.columns([0.5,1,0.5,1,0.5])

            with col1:
                st.markdown("<label style='font-size:20px; font-weight:800;'>Start Date</label>", unsafe_allow_html=True)
            with col2:
                start_date = st.date_input(
                    "", value=data_min,
                    min_value=data_min, max_value=data_max,
                    key="start_date_input", label_visibility="collapsed"
                )

            with col3:
                st.markdown("<label style='font-size:20px; font-weight:800;'>End Date</label>", unsafe_allow_html=True)
            with col4:
                end_date = st.date_input(
                    "", value=data_max,
                    min_value=data_min, max_value=data_max,
                    key="end_date_input", label_visibility="collapsed"
                )

            with col5:
                submitted = st.form_submit_button("Show", use_container_width=True)

        if not submitted:
            return pd.DataFrame(),None,None,None,None,None,None,None,None,None,None,None,None

        if not start_date or not end_date or start_date > end_date:
            st.warning("Please select valid Start and End Dates.")
            return pd.DataFrame(),None,None,None,None,None,None,None,None,None,None,None,None
        # ---------------- Compute from DuckDB ONLY ----------------
        calc_raw = compute_all_38_duckdb(
            start_date=str(start_date),
            end_date=str(end_date),
            parquet_root=PARQUET_ROOT,
        )
        if calc_raw is None or calc_raw.empty:
            st.info("No loans in the selected range.")
            return pd.DataFrame(),None,None,None,None,None,None,None,None,None,None,None,None

        # ---------------- Build the 7-column table you requested ----------------
        df = calc_raw.copy()
        actual = {c.lower(): c for c in df.columns}
        def pick(name: str) -> str:
            k = name.lower()
            if k not in actual:
                raise KeyError(f"Missing expected column in calculator output: {name}")
            return actual[k]

        c_loan   = pick("loan_id")
        c_disb   = pick("disb_date")
        c_amt30  = pick("amount_repaid_within_30_days")
        c_iacc30 = pick("interest_accrued_30")
        c_ipd30  = pick("interest_paid_30")
        c_ppd30  = pick("principal_paid_30")
        c_out30  = pick("outstanding_after_30_days")

        show_df = df[[c_loan, c_disb, c_amt30, c_iacc30, c_ipd30, c_ppd30, c_out30]].rename(columns={
            c_loan:  "Loan ID",
            c_disb:  "Disbursement Date",
            c_amt30: "Amount Paid",
            c_iacc30:"Interest Chargeble",
            c_ipd30: "Interest Paid",
            c_ppd30: "Pricipal Paid",
            c_out30: "Balance",
        })

        show_df["Disbursement Date"] = pd.to_datetime(show_df["Disbursement Date"], errors="coerce").dt.date
        for nc in ["Amount Paid", "Interest Chargeble", "Interest Paid", "Pricipal Paid", "Balance"]:
            show_df[nc] = pd.to_numeric(show_df[nc], errors="coerce").fillna(0.0)

        # ---------------- KPIs (based on the 7 fields) ----------------
        total_amount_paid      = float(show_df["Amount Paid"].sum())
        total_interest_charge  = float(show_df["Interest Chargeble"].sum())
        total_interest_paid    = float(show_df["Interest Paid"].sum())
        total_principal_paid   = float(show_df["Pricipal Paid"].sum())
        total_balance          = float(show_df["Balance"].sum())

        # define an overall “paid%” of (principal+interest paid) vs (principal+interest paid + balance)
        paid_denom = total_principal_paid + total_interest_paid + total_balance
        paid_pct   = (total_principal_paid + total_interest_paid) / paid_denom * 100 if paid_denom > 0 else 0.0

        # (Optional) a utilization “within-30” ratio: Amount Paid vs (Amount Paid + Balance)
        within30_denom = total_amount_paid + total_balance
        within30_paid_pct = (total_amount_paid / within30_denom * 100) if within30_denom > 0 else 0.0

        # ---------------- KPI cards (kept, but fed with new totals) ----------------
        st.markdown("""
            <style>
            :root {
                --brand:#1f6feb; --brand-2:#0ea5e9; --success:#10b981; --warning:#f59e0b; --danger:#ef4444; --indigo:#7c3aed;
                --surface:#ffffff; --surface-2:#fbfdff; --border:rgba(30,65,103,.08); --shadow:0 6px 14px rgba(18,38,63,.06);
                --shadow-hover:0 10px 22px rgba(18,38,63,.10); --title:#6b7280; --value:#0f172a;
            }
            @media (prefers-color-scheme: dark) {
                :root { --surface:#0b1220; --surface-2:#0f1626; --border:rgba(255,255,255,.08); --shadow:0 6px 14px rgba(0,0,0,.35);
                        --shadow-hover:0 10px 22px rgba(0,0,0,.45); --title:#9aa4b2; --value:#eef2ff; }
            }
            .stat-card{
                background:linear-gradient(180deg,var(--surface) 0%,var(--surface-2) 100%);
                border-radius:14px; padding:14px 16px; box-shadow:var(--shadow); border:1px solid var(--border);
                min-height:96px; transition:transform .14s, box-shadow .14s, border-color .14s; position:relative; overflow:hidden; isolation:isolate;
            }
            .stat-card:hover{ transform: translateY(-3px); box-shadow: var(--shadow-hover); }
            .stat-card::before{content:""; position:absolute; inset:0 0 auto 0; height:3px; background:var(--accent,var(--brand)); opacity:.9; z-index:1;}
            .stat-title{ font-size:22px; color:var(--title); font-weight:700; margin:2px 0 4px 0; }
            .stat-value{ font-size:22px; font-weight:700; color:var(--value); margin:0; }
            .theme-brand{ --accent:var(--brand); }
            .theme-success{ --accent:var(--success); }
            .theme-warning{ --accent:var(--warning); }
            .theme-danger{ --accent:var(--danger); }
            .theme-indigo{ --accent:var(--indigo); }
            .theme-cyan{ --accent:var(--brand-2); }
            </style>
        """, unsafe_allow_html=True)

        rows = [
            [
                (f"Amount Paid ({CURRENCY_CODE})",       f"{total_amount_paid:,.2f}",         "theme-success"),
                (f"Interest Chargeble ({CURRENCY_CODE})",f"{total_interest_charge:,.2f}",     "theme-warning"),
                (f"Interest Paid ({CURRENCY_CODE})",     f"{total_interest_paid:,.2f}",       "theme-cyan"),
                (f"Balance ({CURRENCY_CODE})",           f"{total_balance:,.2f}",             "theme-danger"),
            ],
            [
                (f"Principal Paid ({CURRENCY_CODE})",    f"{total_principal_paid:,.2f}",      "theme-brand"),
                ("Paid % ",                  f"{paid_pct:.2f}%",                  "theme-indigo"),
                ("Within-30 Paid %",                     f"{within30_paid_pct:.2f}%",         "theme-indigo"),
                ("Loans ",                        f"{len(show_df):,}",                 "theme-brand"),
            ],
        ]
        for row in rows:
            cols = st.columns(len(row))
            for col, (title, value, theme) in zip(cols, row):
                with col:
                    st.markdown(f"""
                        <div class="stat-card {theme}">
                            <div class="stat-title">{title}</div>
                            <div class="stat-value">{value}</div>
                        </div>
                    """, unsafe_allow_html=True)

        st.markdown("<hr/>", unsafe_allow_html=True)

        # ---------------- Charts: monthly/daily using new columns ----------------
        # For trends, we’ll visualize Amount Paid (area) vs Principal Paid (line)
        df_dates = show_df.copy()
        df_dates["Date"] = pd.to_datetime(df_dates["Disbursement Date"], errors="coerce")
        df_dates = df_dates.dropna(subset=["Date"])
        if df_dates.empty:
            st.warning("No data to plot.")
        else:
            dates_norm = df_dates["Date"].dt.normalize().sort_values()
            unique_dates = np.unique(dates_norm)
            if len(unique_dates) < 2:
                is_monthly = False
            else:
                diffs = np.diff(unique_dates).astype("timedelta64[D]").astype(int)
                median_gap = int(np.median(diffs))
                idx = pd.DatetimeIndex(unique_dates)
                aligned_ratio = max((idx.day == 1).mean(), idx.is_month_end.mean())
                is_monthly = (median_gap >= 20) or (aligned_ratio >= 0.70)

            def themed_note(text, theme_class="theme-indigo"):
                st.markdown(f"""
                    <div class="stat-card {theme_class}" style="margin: 6px 2px;">
                        <div class="stat-title" style="font-size:16px;margin:0;">{text}</div>
                    </div>
                """, unsafe_allow_html=True)

            if is_monthly:
                themed_note("Detected monthly data — rendering monthly trend.")
                mdf = (
                    df_dates.set_index("Date")
                    .resample("M")
                    .agg({"Amount Paid": "sum", "Pricipal Paid": "sum"})
                    .reset_index()
                )
                mdf["Date"] = mdf["Date"].dt.to_period("M").dt.to_timestamp()

                # reuse your seaborn/matplotlib function with new column names
                streamlit_daily_area_line_seaborn(
                    mdf,
                    value_col="Amount Paid",
                    repay_col="Pricipal Paid",
                    default_window_days=len(mdf),
                    max_ticks=9,
                    dark=False,
                    currency_code=CURRENCY_CODE,
                )


            else:
                ddf = df_dates.copy()
                ddf["Date"] = ddf["Date"].dt.normalize()
                ddf = ddf.groupby("Date", as_index=False).agg({
                    "Amount Paid": "sum",
                    "Pricipal Paid": "sum"
                })
                full_idx = pd.date_range(ddf["Date"].min(), ddf["Date"].max(), freq="D")
                ddf = (
                    ddf.set_index("Date")
                       .reindex(full_idx)
                       .fillna(0.0)
                       .rename_axis("Date")
                       .reset_index()
                )
                MAX_DAYS_TO_PLOT = 365
                if len(ddf) > MAX_DAYS_TO_PLOT:
                    themed_note(f"Large daily range detected — plotting last {MAX_DAYS_TO_PLOT} days.", "theme-warning")
                    ddf = ddf.tail(MAX_DAYS_TO_PLOT).reset_index(drop=True)

                left_col, right_col = st.columns([1.45, 1], vertical_alignment="top")
                with left_col:
                    streamlit_daily_area_line_seaborn(
                        ddf,
                        value_col="Amount Paid",
                        repay_col="Pricipal Paid",
                        default_window_days=30,
                        max_ticks=9,
                        dark=False,
                    )
                with right_col:
                    # donut: Principal Paid vs Interest Paid vs Balance
                    plot_donut_paid_interest_balance(
                        principal_paid=total_principal_paid,
                        interest_paid=total_interest_paid,
                        balance=total_balance
                    )

        # ---------------- Data table ----------------
        show_df = show_df.sort_values(["Disbursement Date", "Loan ID"], na_position="last")
        show_df.index = range(1, len(show_df) + 1)
        st.dataframe(show_df, use_container_width=True, height=320)

        # ---------------- Download & Print ----------------
        capture_script = """
        <style>
        .button-container { display:flex; gap:10px; align-items:center; }
        .download-btn {
            background-color:#4CAF50; color:white; padding:12px 24px; border:none; border-radius:10px;
            font-size:16px; font-weight:bold; cursor:pointer; box-shadow:0 4px 6px rgba(0,0,0,.2); transition:all .3s;
        }
        .download-btn:hover { background-color:#45a049; transform:scale(1.05); box-shadow:0 6px 12px rgba(0,0,0,.3); }
        .download-btn:active { transform:scale(.98); background-color:#3e8e41; }
        </style>
        <div class="button-container">
            <button class="download-btn" onclick="window.parent.print()">📸 Print / Save PDF</button>
            <div id="excel-button"></div>
        </div>
        """
        st.components.v1.html(capture_script, height=80)

        def to_excel(df_):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_.to_excel(writer, index=False, sheet_name="Disbursements")
            return output.getvalue()

        excel_file = to_excel(show_df)
        st.download_button(
            label="📥 Download Excel",
            data=excel_file,
            file_name="disbursements_0-30_days.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # return signature preserved
        return show_df,None,None,None,None,None,None,None,None,None,None,None,None

    except Exception as e:
        st.error(f" Error fetching disbursement data: {str(e)}")
        return pd.DataFrame(),None,None,None,None,None,None,None,None,None,None,None,None
