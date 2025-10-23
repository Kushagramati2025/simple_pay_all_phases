# full_report.py
import streamlit as st
import pandas as pd
from datetime import date
import io
from streamlit_echarts import st_echarts
import streamlit.components.v1 as components
from pathlib import Path
import duckdb, os


from tools.config_paths import PARQUET_ROOT, DISB_GLOB, RECV_GLOB
from Calculation.loan_duckdb import compute_all_38_duckdb, load_config, LoanCalcConfig


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "loan_rules.json"
RULES = load_config(CONFIG_PATH)  # will merge defaults + env vars + JSON overrides


# Normalize to POSIX (forward slashes) and use recursive glob pattern


@st.cache_resource
def get_duck():
    db = duckdb.connect()                      # in-process
    db.execute("PRAGMA disable_progress_bar")
    db.execute(f"SET threads TO {os.cpu_count() or 4}")
    return db

# ---------- helper: grouped KPI rows using your EXACT column names ----------


def render_grouped_totals_exact(df: pd.DataFrame):
    """
    Shows one horizontal KPI line per business category using your exact SQL aliases.
    Will only display cards for columns that actually exist in df.
    """

    if df is None or df.empty:
        st.info("No data for totals.")
        return

    # numeric totals
    num_df = df.select_dtypes(include="number")
    if num_df.empty:
        st.info("No numeric columns for totals.")
        return
    totals = num_df.sum(numeric_only=True)

    # --- exact names from your SELECT (with a couple of fallbacks) ---
    # If you later keep the rename disb_amount -> "Loan Amount", we handle both.
    principal_group = [
        # disbursement / principal paid / balances
        "disb_amount", "Loan Amount",
        "Principal_paid_30", "Principal_paid_31_45", "Principal_paid_46_60", "Principal_paid_61_90",
        "principal_balance_31_45", "principal_balance_46_60", "principal_balance_61_90",
    ]

    interest_group = [
        "Interest_accrued_30", "Interest_paid_30",
    ]

    penalty_group = [
        "Penalty_31_45", "Penalty_paid_31_45", "Penalty_balance_31_45",
        "Penalty_46_60", "Penalty_paid_46_60", "Penalty_balance_46_60",
        "Penalty_61_90", "Penalty_paid_61_90", "Penalty_balance_61_90",
    ]

    receipts_group = [
        "Amount_repaid_within_30_days",
        "Amount_Received_within_31_to_45_days",
        "Amount_Received_within_46_to_60_days",
        "Amount_Received_within_61_to_90_days",
    ]

    outstanding_group = [
        "Outstanding_after_30_days",
        "Outstanding_after_45_days",
        "Outstanding_after_60_days",
        "Outstanding_after_90_days",
    ]

    # Keep order + only keep columns that exist in df
    def existing(cols): return [c for c in cols if c in totals.index]

    groups = [
        ("Interest Totals",   existing(interest_group)),
        ("Principal Totals",  existing(principal_group)),
        ("Penalty Totals",    existing(penalty_group)),
        ("Receipts Totals",   existing(receipts_group)),
        ("Outstanding Totals",existing(outstanding_group)),
    ]

    theme_cycle = ["theme-brand","theme-success","theme-indigo","theme-warning","theme-danger","theme-cyan"]

    st.markdown("</div>", unsafe_allow_html=True)

    for g_idx, (title, cols_in_group) in enumerate(groups):
        if not cols_in_group:
            continue

        st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)

        # --- Special handling: split Penalty Totals into multiple rows ---
        if title == "Penalty Totals":
            chunk_size = 4   #  keep 4 items per row; change to 3/5 if you prefer
            for ch, start in enumerate(range(0, len(cols_in_group), chunk_size)):
                sub_cols = cols_in_group[start:start + chunk_size]
                row = [(c, totals[c]) for c in sub_cols]
                cols = st.columns(len(row))
                for i, ((label, val), slot) in enumerate(zip(row, cols)):
                    theme = theme_cycle[(g_idx + i + ch) % len(theme_cycle)]
                    with slot:
                        st.markdown(
                            f"""
                            <div class="stat-card {theme}">
                                <div class="stat-title">{label}</div>
                                <div class="stat-value">{_fmt_money(val)}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
            continue  # skip default rendering for this group

        # --- Default rendering for all other groups (one row) ---
        row = [(c, totals[c]) for c in cols_in_group]
        cols = st.columns(len(row))
        for i, ((label, val), slot) in enumerate(zip(row, cols)):
            theme = theme_cycle[(g_idx + i) % len(theme_cycle)]
            with slot:
                st.markdown(
                    f"""
                    <div class="stat-card {theme}">
                        <div class="stat-title">{label}</div>
                        <div class="stat-value">{_fmt_money(val)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

from simple_pay.utils.database_connection import DatabaseConnectionPool
from simple_pay.service.helper import get_selected_currency_code, get_currency_name_by_code

@st.cache_resource
def _init_mysql_pool():
    # tune pool_size to your box
    DatabaseConnectionPool.init_pool(
        host="localhost",
        user="root",
        password="",
        database="keny",
        pool_name="st_pool",
        pool_size=16,
        connection_timeout=20,
        autocommit=False,          # safe default; we only SELECT here
        allow_local_infile=True,
        use_pure=True,
    )
    return True

def _db_conn():
    _init_mysql_pool()
    # return a fresh, pooled connection *each* call
    return DatabaseConnectionPool.get_connection()

@st.cache_data(ttl=60)
def get_currency_symbol_by_code(code: str) -> str | None:
    if not code:
        return None
    conn = _db_conn()
    try:
        cur = conn.cursor()
        # Try common column names for symbol; keep whichever you actually have
        for col in ("symbol", "symbol_prefix", "symbol_char"):
            try:
                cur.execute(f"SELECT {col} FROM currency WHERE code=%s LIMIT 1;", (code,))
                row = cur.fetchone()
                if row and row[0]:
                    return row[0]
            except Exception:
                continue
        return None
    finally:
        try: cur.close()
        except: pass
        conn.close()

def _currency_ctx():
    """Return (CODE, NAME, SYMBOL) from DB with graceful fallbacks."""
    code = (get_selected_currency_code() or "INR").upper()
    name = get_currency_name_by_code(code) or code
    symbol = get_currency_symbol_by_code(code) or ("₹" if code == "INR" else code + " ")
    return code, name, symbol



def _fmt_money(n: float, symbol: str | None = None, decimals: int = 2) -> str:
    try:
        if symbol is None:
            # fallback to whatever we stored when we built the page
            symbol = st.session_state.get("currency_symbol", "₹")
        return f"{symbol}{float(n):,.{decimals}f}"
    except Exception:
        symbol = symbol or st.session_state.get("currency_symbol", "₹")
        return f"{symbol}0.00"


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

capture_script = """
<style>
button {
    position: fixed;
    bottom: 30px;
    right: 30px;
    z-index: 1000;
    background: #22c55e;
    color: white;
    padding: 12px 20px;
    border: none;
    border-radius: 25px;
    font-size: 14px;
    font-weight: bold;
    cursor: pointer;
    box-shadow: 0 4px 8px rgba(0,0,0,0.3);
}
button:hover { background: #16a34a; transform: translateY(-2px); }
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/dom-to-image-more@3.2.0/dist/dom-to-image-more.min.js"></script>
<script>
function downloadImage(){ window.parent.print() }
function downloadPDF(){
  html2canvas(window.parent.document.body).then(function(canvas) {
    const { jsPDF } = window.jspdf;
    const pdf = new jsPDF("p", "pt", "a4");
    const imgData = canvas.toDataURL("image/png");
    const imgProps = pdf.getImageProperties(imgData);
    const pdfWidth = pdf.internal.pageSize.getWidth();
    const pdfHeight = (imgProps.height * pdfWidth) / imgProps.width;
    pdf.addImage(imgData, "PNG", 0, 0, pdfWidth, pdfHeight);
    pdf.save("page.pdf");
  });
}
</script>
<button onclick="downloadImage()">📸 Download Dashboard</button>
"""


# ---------------------------
# Custom CSS
# ---------------------------
def set_custom_style():
    st.markdown("""
    <style>
    :root {
        /* Brand palette — tweak just these to re-theme */
        --brand:#1f6feb; --brand-2:#0ea5e9; --success:#10b981; --warning:#f59e0b; --danger:#ef4444; --indigo:#7c3aed;

        /* Neutral surface + text */
        --surface:#ffffff; --surface-2:#fbfdff;
        --border:rgba(30,65,103,0.08);
        --shadow:0 6px 14px rgba(18,38,63,0.06);
        --shadow-hover:0 10px 22px rgba(18,38,63,0.10);
        --title:#6b7280; --value:#0f172a;
    }
    @media (prefers-color-scheme: dark) {
        :root {
            --surface:#0b1220; --surface-2:#0f1626;
            --border:rgba(255,255,255,0.08);
            --shadow:0 6px 14px rgba(0,0,0,0.35);
            --shadow-hover:0 10px 22px rgba(0,0,0,0.45);
            --title:#9aa4b2; --value:#eef2ff;
        }
    }

    /* --- App chrome bits you had --- */
    .main { background-color:#f4f7fa; padding:1.5rem; }
    .report-title { font-size:26px; font-weight:700; color:#0f172a; margin-bottom:1rem; border-left:6px solid #2563eb; padding-left:12px; }
    .range-message { font-size:15px; color:#475569; margin-bottom:.75rem; }
    .stDataFrame { border-radius:12px!important; border:1px solid #e2e8f0!important; margin-bottom:1rem; box-shadow:0 2px 6px rgba(0,0,0,0.04); }

    /* --- Shared card look (your stat-card theme) --- */
    .stat-card {
        background:linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%);
        border-radius:14px; padding:14px 16px;
        box-shadow:var(--shadow); border:1px solid var(--border);
        display:flex; flex-direction:column; justify-content:center;
        min-height:96px; transition:transform .14s ease, box-shadow .14s ease, border-color .14s ease;
        font-family:"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        text-align:left; position:relative; overflow:hidden; isolation:isolate;
    }
    .stat-card:hover { transform:translateY(-3px); box-shadow:var(--shadow-hover); }
    .stat-card::before { content:""; position:absolute; inset:0 0 auto 0; height:3px; background:var(--accent, var(--brand)); opacity:.9; z-index:1; }
    .stat-title { font-size:13px; color:var(--title); font-weight:700; margin:0 0 6px 0; line-height:1.2; letter-spacing:.2px; text-transform:uppercase; }
    .stat-value { font-size:20px; font-weight:800; color:var(--value); margin:0; line-height:1.15; }

    /* Theme variants */
    .theme-brand  { --accent:var(--brand);  background:linear-gradient(180deg, color-mix(in oklab, var(--brand) 8%, var,--surface)) 0%, var(--surface-2) 85%);  border-color:color-mix(in oklab, var(--brand) 18%, var,--border)); }
    .theme-cyan   { --accent:var(--brand-2);background:linear-gradient(180deg, color-mix(in oklab, var(--brand-2)10%, var,--surface))0%, var(--surface-2)85%); border-color:color-mix(in oklab, var,--brand-2)18%, var,--border));}
    .theme-success{ --accent:var(--success);background:linear-gradient(180deg, color-mix(in oklab, var(--success)10%, var,--surface))0%, var(--surface-2)85%); border-color:color-mix(in oklab, var,--success)18%, var,--border));}
    .theme-warning{ --accent:var(--warning);background:linear-gradient(180deg, color-mix(in oklab, var(--warning)10%, var,--surface))0%, var(--surface-2)85%); border-color:color-mix(in oklab, var,--warning)18%, var,--border));}
    .theme-danger { --accent:var(--danger); background:linear-gradient(180deg, color-mix(in oklab, var(--danger) 10%, var,--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var,--danger) 18%, var,--border));}
    .theme-indigo { --accent:var(--indigo); background:linear-gradient(180deg, color-mix(in oklab, var(--indigo) 10%, var,--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var,--indigo) 18%, var,--border));}

    /* --- Totals section that reuses stat-card look --- */
    .totals-wrap { margin-top:12px; }
    .section-title {
        font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.04em;
        color:var(--title); margin:16px 2px 8px;
    }
    .totals-grid {
        display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:10px;
    }
    .total-card { /* extend stat-card feel */
        position:relative;
        background:linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%);
        border-radius:14px; padding:12px 14px; box-shadow:var(--shadow); border:1px solid var(--border);
        min-height:64px; display:grid; grid-template-columns:1fr auto; align-items:center;
    }
    .total-card::before { content:""; position:absolute; inset:0 0 auto 0; height:3px; background:var(--accent, var(--brand)); opacity:.9; }
    .total-label { font-size:13px; color:var(--title); font-weight:700; }
    .total-value { font-weight:800; font-size:15px; color:var(--value); }

    /* spacing tighteners */
    div[data-testid^="stDateInput"], div[data-testid*="date_input"]{margin-bottom:0!important;padding-bottom:0!important;}
    div[data-testid^="stHorizontalBlock"]{margin-top:0!important;padding-top:0!important;}
    div[data-testid^="stVerticalBlock"]>div[data-testid^="stHorizontalBlock"]{margin-top:0!important;padding-top:0!important;}
    [data-testid="stMetric"],[data-testid="stCard"],.stMetric,.stCard{margin-top:0!important;margin-bottom:0!important;padding-top:0!important;padding-bottom:0!important;}
    @media (min-width:1000px){ .stat-card, .total-card{ margin:4px!important; } }
    @media (max-width:520px){ .total-card{ grid-template-columns:1fr; row-gap:6px; } .total-value{ justify-self:start; } }
    /* --- Thin bold line between graph and pie chart --- */
    hr {
        height: 3px !important;
        background-color: #0f172a !important;
        border: none !important;
        margin: 2rem 0 !important;
        opacity: 0.8 !important;
    }   

                /* --- Vertical line between graph and pie chart --- */
    .vertical-divider {
        border-left: 3px solid #0f172a  !important;
        height: 100%  !important;
        margin: 0 1rem !important;
        opacity: 0.8  !important;
    }         
/* --- Table container for graph and chart --- */
.graph-chart-container {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
    border: 2px solid #000000;
    border-radius: 8px;
    overflow: hidden;
    margin: 10px 0;
}

.graph-cell, .chart-cell {
    padding: 10px;
    min-height: 400px;
}

.graph-cell {
    border-right: 2px solid #000000;
}

    """, unsafe_allow_html=True)

# -----------------------
# Optimized SQL
# -----------------------

# -----------------------
# Palette + plotting helpers (NEW)
# -----------------------
THEME_PALETTE = {
    "brand":   "#1f6feb",
    "brand2":  "#0ea5e9",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger":  "#ef4444",
    "indigo":  "#7c3aed",
    "title":   "#6b7280",
    "value":   "#0f172a",
    "muted":   "#64748b",
}

def add_top_right_close_button(offset_top: int = 0, target_page: str = "pages/Reports.py"):
    """
    Adds a fixed red cancel button at the top-right corner that switches to another page.

    Args:
        offset_top: vertical offset in pixels (default 0 for very top)
        target_page: relative path to the target page inside your app
    """
    # # Only show the top-right button (no left-side button)
    




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

    center_amount_text = _fmt_money(grand_total)
    center_paid_text   = f"Paid {grand_total_paid_pct:.1f}%"

    data_points = [
        {"name": "Disbursed",      "value": [amount_disbursed,      _fmt_money(amount_disbursed)]},
        {"name": "Principal Paid", "value": [amount_principal_paid, _fmt_money(amount_principal_paid)]},
        {"name": "Interest Paid",  "value": [amount_interest_paid,  _fmt_money(amount_interest_paid)]},
    ]

    options = {
        "color": [THEME_PALETTE["brand"], THEME_PALETTE["success"], THEME_PALETTE["warning"]],
        "animationDuration": 800,
        "animationEasing": "cubicOut",
        "tooltip": {"trigger": "item", "formatter": "{b}<br/>{@[1]}<br/>{d}%"},
        "legend": {
            "orient": "horizontal", "bottom": 0, "itemGap": 16,
            "textStyle": {"color": THEME_PALETTE["title"], "fontSize": 12}
        },
        "series": [{
            "name": "Amounts", "type": "pie",
            "radius": ["45%", "70%"], "center": ["50%", "50%"],
            "avoidLabelOverlap": True, "stillShowZeroSum": True, "clockwise": True,
            "itemStyle": {"borderRadius": 8, "borderColor": "#ffffff", "borderWidth": 2},
            "label": {
                "show": True, "formatter": "{b}\n{@[1]} ({d}%)",
                "fontSize": 15, "lineHeight": 16, "color": THEME_PALETTE["value"]
            },
            "emphasis": {"scale": True, "scaleSize": 3,
                "itemStyle": {"shadowBlur": 12, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.25)"}
            },
            "data": data_points
        }],
        "graphic": [{
            "type": "group", "left": "center", "top": "45%", "z": 100,
            "children": [
                {"type": "text", "style": {
                    "text": center_amount_text, "textAlign": "center",
                    "fontSize": 14, "fontWeight": 700, "fill": THEME_PALETTE["value"]
                }},
                {"type": "text", "top": 18, "style": {
                    "text": center_paid_text, "textAlign": "center",
                    "fontSize": 11, "fill": THEME_PALETTE["muted"]
                }},
            ]
        }]
    }
    st_echarts(options=options, height="360px", key="advanced_ring_pie")

def streamlit_daily_area_line_seaborn(
    filtered_df,
    value_col="Principal",
    repay_col="Principal Paid",
    default_window_days=30,
    max_ticks=9,
    *,
    dark=False,
    theme_colors=None,
):
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    import seaborn as sns
    from matplotlib.ticker import FuncFormatter

    default_light = dict(
        brand="#1f6feb", brand2="#0ea5e9", success="#10b981", warning="#f59e0b",
        danger="#ef4444", indigo="#7c3aed", surface="#ffffff", surface2="#fbfdff",
        border_rgba=(30/255, 65/255, 103/255, 0.08), title="#6b7280",
        value="#0f172a", grid_rgba=(0.4, 0.4, 0.4, 0.18),
    )
    default_dark = dict(
        brand="#1f6feb", brand2="#0ea5e9", success="#10b981", warning="#f59e0b",
        danger="#ef4444", indigo="#7c3aed", surface="#0b1220", surface2="#0f1626",
        border_rgba=(1, 1, 1, 0.08), title="#9aa4b2",
        value="#eef2ff", grid_rgba=(1, 1, 1, 0.22),
    )
    C = {**(default_dark if dark else default_light), **(theme_colors or {})}


    if filtered_df is None or len(filtered_df) == 0:
        st.warning("No data to plot.")
        return

    df = filtered_df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Date"])
    if df.empty:
        st.warning("No valid dates after parsing.")
        return
    for col in [value_col, repay_col]:
        if col not in df.columns:
            st.error(f"Missing required column: {col}")
            return

    daily = df.groupby("Date", as_index=True).agg({value_col: "sum", repay_col: "sum"})
    if daily.empty:
        st.warning("No daily rows after aggregation.")
        return

    full_idx = pd.date_range(daily.index.min(), daily.index.max(), freq="D")
    daily = daily.reindex(full_idx, fill_value=0).rename_axis("Date").reset_index()

    n = len(daily)
    plot_df = daily.tail(default_window_days).reset_index(drop=True) if n > default_window_days else daily.reset_index(drop=True)

    sns.set_style("whitegrid")
    plt.rcParams.update({
        "axes.titlesize": 15, "axes.titleweight": "bold",
        "axes.labelsize": 11, "legend.frameon": True,
        "legend.fontsize": 9, "figure.autolayout": True,
    })
    fig, ax = plt.subplots(figsize=(10, 4.6), dpi=110)
    fig.patch.set_facecolor(C["surface"])
    ax.set_facecolor(C["surface2"])
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color(C["border_rgba"])
        spine.set_linewidth(1)

    import numpy as np
    x = np.arange(len(plot_df))
    disb_color = C["brand"]
    repay_color = "#ef4444"
    trend_color = C["title"]

    ax.fill_between(x, plot_df[value_col], step="mid", alpha=0.30, color=disb_color, label="Loan Disbursement", zorder=2)
    ax.bar(x, plot_df[value_col], color=disb_color, alpha=0.14, width=0.9, zorder=1)
    ax.plot(x, plot_df[repay_col], color=repay_color, marker="o", linewidth=2.2, markersize=5.5, label="Loan Repayment", zorder=3)

    if len(plot_df) > 1 and float(plot_df[value_col].sum()) > 0:
        coeff = np.polyfit(x, plot_df[value_col], 1)
        ax.plot(x, np.poly1d(coeff)(x), ls="--", color=trend_color, linewidth=1.3, label="Trend", zorder=2)

    top_n = min(3, len(plot_df))
    for i in plot_df[value_col].nlargest(top_n).index.tolist():
        y = float(plot_df[value_col].iloc[i])
        if y > 0:
             ax.annotate(
                f"{y:,.0f}", xy=(i, y), xytext=(0, 8), textcoords="offset points",
                ha="center", fontsize=9, color=disb_color, weight="bold", zorder=5
            )

    rep_max = float(plot_df[repay_col].max()) if len(plot_df) else 0
    denom = max(2, (max_ticks or 0))
    step = max(1, len(plot_df) // (denom - 1))
    y_pad = float(max(1e-9, plot_df[value_col].max())) * 0.02
    for i in range(0, len(plot_df), step):
        y = float(plot_df[repay_col].iloc[i])
        if y > 0 or y == rep_max:
                        ax.text(i, y + y_pad, f"{y:,.0f}", ha="center", va="bottom",
                            fontsize=8, color=repay_color)


    ax.set_title("Disbursement vs. Repayment Trend", fontsize=16, weight="700", color=C["value"])
    ax.set_xlabel("Day", color=C["title"], labelpad=6)
    ax.set_ylabel("Amount", color=C["title"], labelpad=6)

    n_plot = len(plot_df)
    safe_max_ticks = max(1, int(max_ticks) if isinstance(max_ticks, (int, float)) else 9)
    tick_step = max(1, n_plot // safe_max_ticks)
    tick_idx = list(range(0, n_plot, tick_step))
    tick_labels = [pd.to_datetime(plot_df["Date"]).dt.strftime("%d %b").iloc[i] for i in tick_idx]
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_labels, rotation=0, fontsize=9, color=C["title"])
    ax.tick_params(axis="y", labelsize=9, colors=C["title"])

    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))

    ax.grid(axis="y", linestyle=(0, (2, 4)), linewidth=0.7, color=C["grid_rgba"], alpha=1.0)
    ax.set_axisbelow(True)

    leg = ax.legend(loc="upper right")
    leg.get_frame().set_facecolor(C["surface"])
    leg.get_frame().set_edgecolor(C["border_rgba"])
    leg.get_frame().set_linewidth(1.0)
    for text in leg.get_texts():
        text.set_color(C["title"])

    import streamlit as st
    st.pyplot(fig, use_container_width=False)

# -----------------------
# Cached DB helpers
# -----------------------

@st.cache_data(show_spinner=True, ttl=300)
def export_csv_all(df: pd.DataFrame, numeric_cols: list) -> bytes:
    buf = io.StringIO()
    df_to_write = df.copy()
    # ensure numeric columns are numeric exactly like on-screen
    for c in numeric_cols:
        if c in df_to_write.columns:
            df_to_write[c] = pd.to_numeric(df_to_write[c], errors="coerce").fillna(0).round(2)
    df_to_write.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")

# -----------------------
# Report UI
# -----------------------
def loan_detail_report(
    numeric_cols: list | None = None,
    session_prefix: str = "loan_detail",
):


    set_custom_style()
    st.markdown("""
        <style>
        /* Hide Streamlit's default header and toolbar */
        header[data-testid="stHeader"] { 
            display: none !important; 
        }
        div[data-testid="stToolbar"] { 
            display: none !important; 
        }
        </style>
    """, unsafe_allow_html=True)
    st.markdown(
    """
    <style>
    /* Remove top padding in main block */
    .block-container {
        padding-top: 1rem !important;  /* default is ~6rem */
    }

    /* Optional: also reduce bottom padding if needed */
    .block-container {
        padding-bottom: 1rem !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)   
    # Horizontal line between graph/chart and tabl
    
    st.markdown(
            """
            <style>
            /* Target the form container */
            div[data-testid="stForm"] {
                margin-top: -50px !important;
                top: 0px;
                border: 2px solid #4CAF50;
                padding: 20px;
                border-radius: 12px;
                box-shadow: 0 4px 10px rgba(0,0,0,0.1);
            }

            /* Style labels inside the form */
            div[data-testid="stForm"] label {
                font-weight: bold;
                
            }

            /* Style the form's submit button */
            div[data-testid="stForm"] button {
                border-radius: 8px !important;
                padding: 8px 16px !important;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
    
    CURRENCY_CODE, CURRENCY_NAME, CURRENCY_SYMBOL = _currency_ctx()


    CURRENCY_CODE, CURRENCY_NAME, CURRENCY_SYMBOL = _currency_ctx()

    st.session_state["currency_code"] = CURRENCY_CODE
    st.session_state["currency_name"] = CURRENCY_NAME
    st.session_state["currency_symbol"] = CURRENCY_SYMBOL

  
                # st.switch_page("pages/Reports.py")
    start_key = f"{session_prefix}_start_date"
    end_key   = f"{session_prefix}_end_date"
    form_key  = f"{session_prefix}_date_form"

    if start_key not in st.session_state:
        st.session_state[start_key] = date(2024, 2, 1)
    if end_key not in st.session_state:
        st.session_state[end_key] = date(2024, 2, 29)

    st.markdown('<div class="nav-bar-top">', unsafe_allow_html=True)
    
    with st.form(form_key, clear_on_submit=False):
        # label, input, label, input, show, close
        c1, c2, c3, c4, c5, c6 = st.columns([0.6, 1.0, 0.6, 1.0, 0.8, 0.8])

        with c1:
            st.markdown(
                "<label style='font-size:18px; font-weight:800; margin:0; display:flex; align-items:center;'>Start Date</label>",
                unsafe_allow_html=True
            )
        with c2:
            start = st.date_input(
                "",
                value=st.session_state[start_key],
                key=f"{session_prefix}_start_input",
                label_visibility="collapsed"
            )

        with c3:
            st.markdown(
                "<label style='font-size:18px; font-weight:800; margin:0; display:flex; align-items:center;'>End Date</label>",
                unsafe_allow_html=True
            )
        with c4:
            end = st.date_input(
                "",
                value=st.session_state[end_key],
                key=f"{session_prefix}_end_input",
                label_visibility="collapsed"
            )

        with c5:
            show_clicked = st.form_submit_button("Show Report", use_container_width=True)

        with c6:
            close_clicked = st.form_submit_button("Close", key="close_btn", use_container_width=True)
            if close_clicked:
                st.switch_page("pages/Reports.py")

    # Remove this unless you actually opened a <div> above
    # st.markdown("</div>", unsafe_allow_html=True)

    # Guard: only proceed when Show Report was clicked
    if not show_clicked:
        st.info("Pick a start and end date, then click **Show report**.")
        st.stop()

    # Persist + validate
    st.session_state[start_key] = start
    st.session_state[end_key] = end
    if start > end:
        st.warning("Start Date cannot be after End Date.")
        st.stop()

    # Safe to format and compute now
    start_str = pd.to_datetime(start).strftime("%Y-%m-%d")
    end_str   = pd.to_datetime(end).strftime("%Y-%m-%d")

    with st.spinner(f"Processing 38-column Full Report for {start_str} → {end_str} ..."):
        df = compute_all_38_duckdb(
            start_date=start_str,
            end_date=end_str,
            parquet_root=PARQUET_ROOT,
            config_path=CONFIG_PATH,
        )
    # ---- Normalize columns from the new SQL to what the UI expects ----
        import numpy as np

        # 1) Simple renames (only if the friendly column doesn't already exist)
        rename_map = {
            "disb_date": "Date of Loan",
            "disb_amount": "Loan Amount",
        }
        for old, new in rename_map.items():
            if old in df.columns and new not in df.columns:
                df.rename(columns={old: new}, inplace=True)

        # 2) Derive rollups if they don't exist (the UI uses these names)
        if "Total Interest Accrued" not in df.columns and "Interest_accrued_30" in df.columns:
            df["Total Interest Accrued"] = df["Interest_accrued_30"].astype(float)

        if "Total Interest Paid" not in df.columns and "Interest_paid_30" in df.columns:
            df["Total Interest Paid"] = df["Interest_paid_30"].astype(float)

        # Sum principal repaid across windows (0–30, 31–45, 46–60, 61–90)
        principal_cols = ["Principal_paid_30", "Principal_paid_31_45",
                        "Principal_paid_46_60", "Principal_paid_61_90"]
        for c in principal_cols:
            if c not in df.columns:
                df[c] = 0.0
        df["Total Principal Repaid (0–90 days)"] = df[principal_cols].sum(axis=1)

        # 3) Safety: ensure numeric for downstream summaries
        for c in ["Loan Amount", "Total Interest Accrued", "Total Interest Paid", "Total Principal Repaid (0–90 days)"]:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

        # 4) Ensure "Date of Loan" exists for the daily chart
        if "Date of Loan" not in df.columns:
            df["Date of Loan"] = pd.NaT

    if df is None or len(df) == 0:
        st.info(f"No records between {start} and {end}.")
        return

    # Infer numeric cols if needed
    if numeric_cols is None:
        numeric_cols = df.select_dtypes(include="number").columns.tolist()

    # KPIs from df
    total_principal      = float(df["Loan Amount"].sum())
    total_interest       = float(df.get("Total Interest Accrued", 0).sum())
    total_interest_paid  = float(df.get("Total Interest Paid", 0).sum())
    total_principal_paid = float(df.get("Total Principal Repaid (0–90 days)", 0).sum())

    kpis = {
        "total_principal": total_principal,
        "total_interest": total_interest,
        "total_interest_paid": total_interest_paid,
        "total_principal_paid": total_principal_paid,
    }

    # Daily series from df
    daily = (
        df.groupby(df["Date of Loan"].astype("datetime64[ns]"))
          .agg({
              "Loan Amount": "sum",
              "Total Principal Repaid (0–90 days)": "sum"
          })
          .reset_index()
          .rename(columns={
              "Date of Loan": "Date",
              "Loan Amount": "Principal",
              "Total Principal Repaid (0–90 days)": "Principal Paid"
          })
          .sort_values("Date")
    )

    # Normalize numeric columns
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).round(2)
    # ================ Styles for KPI cards ================
    st.markdown(
        """
        <style>
        :root {
            --brand:#1f6feb; --brand-2:#0ea5e9; --success:#10b981; --warning:#f59e0b; --danger:#ef4444; --indigo:#7c3aed;
            --surface:#ffffff; --surface-2:#fbfdff; --border:rgba(30,65,103,0.08);
            --shadow:0 6px 14px rgba(18,38,63,0.06); --shadow-hover:0 10px 22px rgba(18,38,63,0.10);
            --title:#6b7280; --value:#0f172a;
        }
        @media (prefers-color-scheme: dark) {
            :root {
                --surface:#0b1220; --surface-2:#0f1626; --border:rgba(255,255,255,0.08);
                --shadow:0 6px 14px rgba(0,0,0,0.35); --shadow-hover:0 10px 22px rgba(0,0,0,0.45);
                --title:#9aa4b2; --value:#eef2ff;
            }
        }

        /* ===== Trim the big blank space on top ===== */
        [data-testid="stAppViewContainer"] > .main { padding-top: 8px !important; }   /* default ~48–64px */
        div[data-testid="block-container"]            { padding-top: 8px !important; }
        div[data-testid="block-container"] > div:first-child { margin-top: 0 !important; }
        section[data-testid="stSidebar"] > div:first-child   { padding-top: 8px !important; }

        /* Optional: uncomment to remove Streamlit header/toolbar entirely */
        /* header[data-testid="stHeader"] { display:none; } */
        /* div[data-testid="stToolbar"] { display:none; } */

        /* Amount tiles */
        .stat-card {
            background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%);
            border-radius: 14px; padding: 14px 16px; box-shadow: var(--shadow); border: 1px solid var(--border);
            display:flex; flex-direction:column; justify-content:center; min-height:96px; transition: transform .14s, box-shadow .14s, border-color .14s;
            font-family:"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; text-align:left; position:relative; overflow:hidden; isolation:isolate;
        }
        .stat-card:hover { transform: translateY(-3px); box-shadow: var(--shadow-hover); }
        .stat-card::before { content:""; position:absolute; inset:0 0 auto 0; height:3px; background:var(--accent, var(--brand)); opacity:.9; z-index:1; }
        .stat-title { font-size: 17px; color: var(--title); font-weight: 700; margin: 0 0 6px 0; line-height:1.2; letter-spacing:.2px; text-transform: uppercase; }
        .stat-value { font-size: 20px; font-weight: 800; color: var(--value); margin: 0; line-height:1.15; }

        .theme-brand  { --accent:var(--brand);  background:linear-gradient(180deg, color-mix(in oklab, var(--brand) 8%, var,--surface)) 0%, var(--surface-2) 85%);  border-color:color-mix(in oklab, var(--brand) 18%, var,--border)); }
        .theme-cyan   { --accent:var(--brand-2);background:linear-gradient(180deg, color-mix(in oklab, var(--brand-2)10%, var,--surface))0%, var(--surface-2)85%); border-color:color-mix(in oklab, var,--brand-2)18%, var,--border));}
        .theme-success{ --accent:var(--success);background:linear-gradient(180deg, color-mix(in oklab, var(--success)10%, var,--surface))0%, var(--surface-2)85%); border-color:color-mix(in oklab, var,--success)18%, var,--border));}
        .theme-warning{ --accent:var(--warning);background:linear-gradient(180deg, color-mix(in oklab, var(--warning)10%, var,--surface))0%, var(--surface-2)85%); border-color:color-mix(in oklab, var,--warning)18%, var,--border));}
        .theme-danger { --accent:var(--danger); background:linear-gradient(180deg, color-mix(in oklab, var(--danger) 10%, var,--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var,--danger) 18%, var,--border));}
        .theme-indigo { --accent:var(--indigo); background:linear-gradient(180deg, color-mix(in oklab, var(--indigo) 10%, var,--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var,--indigo) 18%, var,--border));}

        /* Percentage tiles — distinct look */
        .pct-card {
        --accent: var(--brand);
        background: linear-gradient(180deg, color-mix(in oklab, var(--accent) 6%, var(--surface)) 0%, var(--surface-2) 92%);
        border: 1px dashed color-mix(in oklab, var(--accent) 28%, var,--border));
        min-height: 110px; border-radius:14px; padding: 14px 16px; box-shadow: var(--shadow);
        position:relative; overflow:hidden; isolation:isolate;
        }
        .pct-title { font-size: 13px; color: var(--title); font-weight: 800; letter-spacing:.25px; margin: 2px 0 6px 0; text-transform: uppercase; }
        .pct-value { font-size: 26px; font-weight: 900; color: var(--value); line-height: 1.1; margin: 0 0 8px 0; }
        .pct-progress {
        height: 8px; background: color-mix(in oklab, var(--accent) 10%, var(--surface));
        border-radius: 999px; border: 1px solid color-mix(in oklab, var(--accent) 25%, var,--border)); overflow:hidden;
        }
        .pct-fill {
        height: 100%; width: var(--pct, 0%); background: var(--accent); border-radius: inherit;
        box-shadow: inset 0 -1px 0 rgba(255,255,255,.35); transition: width .25s ease; opacity: .95;
        }
        .pct-card.theme-success { --accent: var(--success); }
        .pct-card.theme-indigo  { --accent: var(--indigo); }
        .pct-card.theme-brand   { --accent: var(--brand);  }

        /* tighten Streamlit spacings for widgets */
        div[data-testid^="stDateInput"], div[data-testid*="date_input"]{margin-bottom:0!important;padding-bottom:0!important;}
        div[data-testid^="stHorizontalBlock"]{margin-top:0!important;padding-top:0!important;}
        div[data-testid^="stVerticalBlock"]>div[data-testid^="stHorizontalBlock"]{margin-top:0!important;padding-top:0!important;}
        [data-testid="stMetric"],[data-testid="stCard"],.stMetric,.stCard{margin-top:0!important;margin-bottom:0!important;padding-top:0!important;padding-bottom:0!important;}

        @media (min-width:1000px){ .stat-card, .pct-card{ margin:4px!important; } }
        </style>
    """,
        unsafe_allow_html=True
    )

    

    # Amount tiles
    # ===== KPIs render (unchanged) =====
    total_outstanding = total_principal + total_interest
    total_paid        = total_principal_paid + total_interest_paid

    principal_paid_pct = (total_principal_paid / total_principal * 100) if total_principal else 0
    interest_paid_pct  = (total_interest_paid  / total_interest  * 100) if total_interest  else 0
    total_paid_pct     = (total_paid / total_outstanding * 100) if total_outstanding else 0


    def _clamp_pct(x: float) -> float:
        try:
            return max(0.0, min(100.0, float(x)))
        except Exception:
            return 0.0
    
    # ===== Render KPI tiles =====
    amount_rows = [
        [("Total Principal",  _fmt_money(total_principal),                                   "theme-brand"),
        ("Principal Paid",   f"{_fmt_money(total_principal_paid)} ({principal_paid_pct:.2f}%)", "theme-success"),
        ("Total Interest",   _fmt_money(total_interest),                                    "theme-cyan"),
        ("Interest Paid",    f"{_fmt_money(total_interest_paid)} ({interest_paid_pct:.2f}%)",   "theme-success")],
        [("Total Outstanding", _fmt_money(total_outstanding),                                "theme-brand"),
        ("Total Paid",        f"{_fmt_money(total_paid)} ({total_paid_pct:.2f}%)",          "theme-indigo")],
    ]


    for row in amount_rows:
        cols = st.columns(len(row))
        for col, (title, value, theme) in zip(cols, row):
            with col:
                st.markdown(
                    f"""
                    <div class="stat-card {theme}">
                        <div class="stat-title">{title}</div>
                        <div class="stat-value">{value}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

    # ===== Render % tiles with progress bars =====
    pct_specs = [
        ("Principal Paid %", principal_paid_pct, "theme-success"),
        ("Interest Paid %",  interest_paid_pct,  "theme-indigo"),
        ("Total Paid %",     total_paid_pct,     "theme-brand"),
    ]
    cols = st.columns(len(pct_specs))
    for col, (title, pct, theme) in zip(cols, pct_specs):
        pct = _clamp_pct(pct)
        with col:
            st.markdown(
                f"""
                <div class="pct-card {theme}">
                    <div class="pct-title">{title}</div>
                    <div class="pct-value">{pct:.2f}%</div>
                    <div class="pct-progress" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{pct:.2f}">
                        <div class="pct-fill" style="--pct:{pct:.2f}%"></div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )

    # (Keep your KPI tiles / CSS here as-is)

    # ===== Charts =====
    st.markdown("<hr/>", unsafe_allow_html=True)
    plot_df = daily[["Date", "Principal", "Principal Paid"]].copy()

    left_col, divider_col, right_col = st.columns([1.45, 0.02, 1], vertical_alignment="top")
    with left_col:
        streamlit_daily_area_line_seaborn(
            plot_df,
            value_col="Principal",
            repay_col="Principal Paid",
            default_window_days=30,
            max_ticks=9,
            dark=False,
        )
    with right_col:
        amount_disbursed       = float(plot_df["Principal"].sum())
        amount_principal_paid  = float(plot_df["Principal Paid"].sum())
        amount_interest_paid   = total_interest_paid
        total_interest_accrued = total_interest
        grand_total            = amount_disbursed + total_interest_accrued
        grand_total_paid       = amount_principal_paid + amount_interest_paid
        grand_total_paid_pct   = (grand_total_paid / grand_total * 100) if grand_total > 0 else 0.0

        plot_advanced_pie_echarts(
            amount_disbursed=amount_disbursed,
            amount_principal_paid=amount_principal_paid,
            amount_interest_paid=amount_interest_paid,
            grand_total=grand_total,
            grand_total_paid_pct=grand_total_paid_pct
        )

    st.markdown('<div style="border-top: 3px solid #000000; margin: 20px 0; width: 100%;"></div>', unsafe_allow_html=True)

    # ===== Table =====
    MAX_PREVIEW = 100_000
    preview = df.head(MAX_PREVIEW)

    st.markdown(
        f'<div class="range-message"> Showing <b>{len(preview):,}</b> (preview) of <b>{len(df):,}</b> rows for '
        f'<b>{start_str}</b> → <b>{end_str}</b>. Download below for full data.</div>',
        unsafe_allow_html=True
    )
    
    preview.index = range(1, len(preview) + 1)
    st.dataframe(preview, use_container_width=True, height=270)

    st.markdown('<div style="border-top: 3px solid #000000; margin: 20px 0; width: 100%;"></div>', unsafe_allow_html=True)

    render_grouped_totals_exact(df)


    # ===== Totals box + CSS (keep your existing render code) =====
    # (Your grouping/SECTION_RULES/WITHIN_ORDER/etc. code goes here unchanged)

    # ===== Download buttons =====
    ca, cb = st.columns([1, 1])

    with ca:
        st.components.v1.html(
            capture_script.replace("position: fixed;", "position: static;"),
            height=60
        )

    with cb:
        def to_excel(df_):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_.to_excel(writer, index=False, sheet_name="Sheet1")
            return output.getvalue()

        excel_file = to_excel(df)
        st.download_button(
            label="📥 Download Table",
            data=excel_file,
            file_name="loan_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
