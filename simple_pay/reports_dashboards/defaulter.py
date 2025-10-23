# defaulter_duck.py — fast, Parquet+DuckDB computation using compute_all_38_duckdb
from __future__ import annotations

from datetime import date
import io

import pandas as pd
import streamlit as st
from streamlit_echarts import st_echarts

# 38-col calculator + data root
from Calculation.loan_duckdb import compute_all_38_duckdb
from tools.config_paths import PARQUET_ROOT

# ======================
# SETTINGS
# ======================
DISB_SUBDIR  = "disbursement"
RECV_SUBDIR  = "receipt"
CONFIG_PATH  = "config/loan_rules.json"

AGE_GATE_DAYS = 90
PAGE_SIZE_DEFAULT = 5  # kept for future use

# --- Currency helpers (same pattern as other pages) ---
from simple_pay.service.helper import get_selected_currency_code, get_currency_name_by_code

@st.cache_data(ttl=60)
def get_currency_symbol_by_code(code: str) -> str | None:
    # Lightweight fallback: INR => ₹, others => "CODE "
    if not code:
        return None
    code = code.upper()
    return "₹" if code == "INR" else f"{code} "

def _currency_ctx():
    """Return (CODE, NAME, SYMBOL) with sensible fallbacks."""
    code = (get_selected_currency_code() or "INR").upper()
    name = get_currency_name_by_code(code) or code
    symbol = get_currency_symbol_by_code(code) or ("₹" if code == "INR" else f"{code} ")
    return code, name, symbol

def fmt_inr_indian_grouping(n: float, decimals: int = 2) -> str:
    try:
        x = float(n)
    except Exception:
        x = 0.0

    neg = x < 0
    x = abs(x)

    # format number with requested decimals; may have no '.' if decimals == 0
    s = f"{x:.{decimals}f}"
    i, dot, d = s.partition(".")

    # Indian grouping for the integer part
    if len(i) <= 3:
        grouped = i
    else:
        last3 = i[-3:]
        head = i[:-3]
        parts = []
        while head:
            parts.append(head[-2:])
            head = head[:-2]
        grouped = ",".join(reversed(parts)) + "," + last3

    # Only add decimals if present (or requested > 0)
    out = grouped if decimals == 0 or dot == "" else grouped + "." + d
    return ("-" if neg else "") + out


def _fmt_money(n: float, symbol: str | None = None, decimals: int = 2) -> str:
    symbol = symbol or st.session_state.get("currency_symbol", "₹")
    return f"{symbol}{fmt_inr_indian_grouping(n, decimals)}"

# =========================================================
# THEME
# =========================================================
THEME_PALETTE = {
    "brand":   "#1f6feb",
    "brand2":  "#0ea5e9",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger":  "#ef4444",
    "indigo":  "#7c3aed",
    "surface":  "#ffffff",
    "surface2": "#fbfdff",
    "title":   "#6b7280",
    "value":   "#0f172a",
    "muted":   "#64748b",
    "border_rgba": "rgba(30, 65, 103, 0.08)",
}
DARK_OVERRIDE = {
    "surface":  "#0b1220",
    "surface2": "#0f1626",
    "title":    "#9aa4b2",
    "value":    "#eef2ff",
    "border_rgba": "rgba(255,255,255,0.08)",
}



def inject_theme_css() -> None:
    p = THEME_PALETTE
    d = DARK_OVERRIDE
    st.markdown(
        f"""
        <style>
        :root {{
            --brand:{p['brand']}; --brand-2:{p['brand2']};
            --success:{p['success']}; --warning:{p['warning']};
            --danger:{p['danger']}; --indigo:{p['indigo']};
            --surface:{p['surface']}; --surface-2:{p['surface2']};
            --border:{p['border_rgba']};
            --title:{p['title']}; --value:{p['value']};
            --shadow:0 6px 14px rgba(18, 38, 63, 0.06);
            --shadow-hover:0 10px 22px rgba(18, 38, 63, 0.10);
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{
                --surface:{d['surface']};
                --surface-2:{d['surface2']};
                --border:{d['border_rgba']};
                --title:{d['title']};
                --value:{d['value']};
                --shadow:0 6px 14px rgba(0,0,0,0.35);
                --shadow-hover:0 10px 22px rgba(0,0,0,0.45);
            }}
        }}
        .main {{ background-color: #f4f7fa; padding: 1.2rem; }}
        .report-title {{
            font-size: 26px; font-weight: 700; color: #2c3e50;
            margin: 0 0 10px 0; border-left: 6px solid #3498db; padding-left: 12px;
        }}
        .stat-card {{
            background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%);
            border-radius: 14px; padding: 14px 16px;
            box-shadow: var(--shadow); border: 1px solid var(--border);
            display:flex; flex-direction:column; justify-content:center;
            min-height:96px; transition:transform .14s ease, box-shadow .14s ease, border-color .14s ease;
            font-family:"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
            text-align:left; position:relative; overflow:hidden; isolation:isolate;
        }}
        .stat-card:hover {{ transform: translateY(-3px); box-shadow: var(--shadow-hover); }}
        .stat-card::before {{
            content:""; position:absolute; inset:0 0 auto 0; height:3px;
            background: var(--accent, var(--brand)); opacity:.9; z-index:1;
        }}
        .stat-title {{ font-size:22px; color:var(--title); font-weight:700; margin:2px 0 4px 0; }}
        .stat-value {{ font-size:22px; font-weight:700; color:var(--value); margin:0; }}
        .theme-brand  {{ --accent: var(--brand);  }}
        .theme-cyan   {{ --accent: var(--brand-2); }}
        .theme-success{{ --accent: var(--success); }}
        .theme-warning{{ --accent: var(--warning); }}
        .theme-danger {{ --accent: var(--danger);  }}
        .theme-indigo {{ --accent: var(--indigo);  }}
        div[data-testid="stForm"] {{
            margin-top:0 !important; border:2px solid #4CAF50; padding:16px 16px 10px 16px;
            border-radius:12px; box-shadow:0 4px 10px rgba(0,0,0,0.08);
        }}
        div[data-testid="stForm"] label {{ font-weight:bold; }}
        div[data-testid="stForm"] button {{ border-radius:8px !important; padding:8px 16px !important; }}
        div[data-testid^="stDateInput"] {{ margin-bottom: 0 !important; }}
        div[data-testid^="stHorizontalBlock"] {{ margin-top: -100 !important; }}
        </style>
        """,
        unsafe_allow_html=True
    )

def stat_card(title: str, value: str, theme: str = "theme-brand"):
    st.markdown(
        f"""
        <div class="stat-card {theme}">
            <div class="stat-title">{title}</div>
            <div class="stat-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

# ======================
# Data layer (DuckDB 38 → filtered defaulters)
# ======================
LOAN_COLS = {
    "date": "Date of Loan",
    "loan": "Loan Number",
    "name": "Loan Account",
    "region": "Region",
    "amt": "Loan Amount",
    "p_bal": "Principal Balance (to 90 days)",
    "i_accr": "Total Interest Accrued",
    "i_paid": "Total Interest Paid",
    "pen_paid": "Total Penalties Paid",
    "pen_bal": "Total Penalties Balance",
    "out_90": "Outstanding after 90 days",
    "status_90": "Status after 90 days",
}

@st.cache_data(show_spinner=True)
def compute_loan_frame(as_of: str) -> pd.DataFrame:
    df = compute_all_38_duckdb(
        start_date="1900-01-01",
        end_date=as_of,
        parquet_root=PARQUET_ROOT,
        disb_subdir=DISB_SUBDIR,
        recv_subdir=RECV_SUBDIR,
        config_path=CONFIG_PATH,
    )

    # map to canonical names (with safe defaults)
    def num(col, default=0.0):
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        # return a Series of the default, aligned to df’s index
        return pd.Series(default, index=df.index, dtype="float64")


    df[LOAN_COLS["date"]]   = pd.to_datetime(df.get("disb_date"), errors="coerce")
    df[LOAN_COLS["loan"]]   = df.get("loan_id", "")
    df[LOAN_COLS["name"]]   = df.get("borrower_name", "")
    df[LOAN_COLS["region"]] = df.get("branch", df.get("Branch", "Unknown")).astype(str)

    df[LOAN_COLS["amt"]]    = num("disb_amount")
    df[LOAN_COLS["i_accr"]] = num("Interest_accrued_30")
    df[LOAN_COLS["i_paid"]] = num("Interest_paid_30")

    df[LOAN_COLS["pen_paid"]] = num("Penalty_paid_31_45") + num("Penalty_paid_46_60") + num("Penalty_paid_61_90")
    df[LOAN_COLS["pen_bal"]]  = num("Penalty_balance_31_45") + num("Penalty_balance_46_60") + num("Penalty_balance_61_90")

    df[LOAN_COLS["p_bal"]]    = num("Principal_balance_61_90")
    df[LOAN_COLS["out_90"]]   = num("Outstanding_after_90_days")

    df[LOAN_COLS["status_90"]] = df.get("status", "").astype(str)

    # enforce numeric types
    for c in [LOAN_COLS["amt"], LOAN_COLS["p_bal"], LOAN_COLS["i_accr"], LOAN_COLS["i_paid"],
              LOAN_COLS["pen_paid"], LOAN_COLS["pen_bal"], LOAN_COLS["out_90"]]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    return df

@st.cache_data(show_spinner=False)
def filter_defaulters(df: pd.DataFrame, as_of: str, age_gate: int = AGE_GATE_DAYS) -> pd.DataFrame:
    as_of_dt = pd.to_datetime(as_of)
    df = df.copy()

    status_col = LOAN_COLS["status_90"]
    out_col    = LOAN_COLS["out_90"]
    date_col   = LOAN_COLS["date"]

    df[status_col] = df[status_col].astype(str).str.upper()
    df[out_col]    = pd.to_numeric(df[out_col], errors="coerce").fillna(0.0)
    df[date_col]   = pd.to_datetime(df[date_col], errors="coerce")

    cond_status = (df[status_col] == "DEFAULTER")
    days = (as_of_dt - df[date_col]).dt.days
    cond_age = (days >= age_gate) & (df[out_col] > 0) & (df[status_col] != "CLOSED")

    return df.loc[cond_status | cond_age].copy()

# ======================
# KPIs & Totals
# ======================
def kpis_from_df(full_df: pd.DataFrame, def_df: pd.DataFrame, as_of: str) -> dict:
    status = full_df[LOAN_COLS["status_90"]].astype(str).str.upper()
    out90  = pd.to_numeric(full_df[LOAN_COLS["out_90"]], errors="coerce").fillna(0.0)

    total_loans   = int(len(full_df))
    active_loans  = int((status == "ACTIVE").sum())
    defaulters    = int((status == "DEFAULTER").sum())

    closed_explicit = int((status == "CLOSED").sum())
    closed_auto     = int(((status != "CLOSED") & (out90 <= 0)).sum())
    closed_loans    = closed_explicit + closed_auto

    return {
        "total_loans": total_loans,
        "active_loans": active_loans,
        "defaulters": defaulters,
        "closed_loans": closed_loans,
        "closed_explicit": closed_explicit,
        "closed_auto": closed_auto,
    }

def totals_from_df(def_df: pd.DataFrame) -> dict:
    p = float(def_df[LOAN_COLS["p_bal"]].sum())
    i = float((def_df[LOAN_COLS["i_accr"]] - def_df[LOAN_COLS["i_paid"]]).clip(lower=0).sum())
    pen = float(def_df[LOAN_COLS["pen_bal"]].sum())
    total = float(def_df[LOAN_COLS["out_90"]].sum())
    return {
        "sum_principal": round(p, 2),
        "sum_interest":  round(i, 2),
        "sum_penalty":   round(pen, 2),
        "sum_total":     round(total, 2),
    }

# ======================
# Charts
# ======================
def plot_status_donut_echarts(kpis: dict, center_note: str | None = None):
    active = int(kpis.get("active_loans", 0))
    closed = int(kpis.get("closed_loans", 0))
    defaulters = int(kpis.get("defaulters", 0))

    data_points = []
    if active > 0:      data_points.append({"name": "Active",    "value": active})
    if closed > 0:      data_points.append({"name": "Closed",    "value": closed})
    if defaulters > 0:  data_points.append({"name": "Defaulter", "value": defaulters})

    total = active + closed + defaulters
    center_amount_text = f"Total\n{total:,}"
    center_paid_text = center_note or "Loan Status"

    options = {
        "color": [THEME_PALETTE["success"], THEME_PALETTE["indigo"], THEME_PALETTE["warning"]],
        "animationDuration": 800,
        "animationEasing": "cubicOut",
        "tooltip": {"trigger": "item", "formatter": "{b}<br/>{c}<br/>{d}%"},
        "legend": {"orient": "horizontal", "bottom": 0, "itemGap": 16,
                   "textStyle": {"color": THEME_PALETTE["title"], "fontSize": 12}},
        "series": [{
            "name": "Status",
            "type": "pie",
            "radius": ["45%", "70%"],
            "center": ["50%", "50%"],
            "avoidLabelOverlap": True,
            "stillShowZeroSum": True,
            "minAngle": 1.5,
            "itemStyle": {"borderRadius": 8, "borderColor": "#ffffff", "borderWidth": 2},
            "label": {"show": True, "formatter": "{b}\n{c} ({d}%)", "fontSize": 15,
                      "lineHeight": 16, "color": THEME_PALETTE["value"]},
            "emphasis": {"scale": True, "scaleSize": 3,
                         "itemStyle": {"shadowBlur": 12, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.25)"}},
            "data": data_points
        }],
        "graphic": [{
            "type": "group", "left": "center", "top": "45%", "z": 100,
            "children": [
                {"type": "text", "style": {"text": center_amount_text, "textAlign": "center",
                                           "fontSize": 16, "fontWeight": 700, "fill": THEME_PALETTE["value"]}},
                {"type": "text", "top": 28, "style": {"text": center_paid_text, "textAlign": "center",
                                                      "fontSize": 11, "fill": THEME_PALETTE["muted"]}}
            ]
        }]
    }
    st_echarts(options=options, height=360, key="status_donut_echarts")

def plot_default_composition_pie_echarts(totals: dict, title_note: str | None = None):
    sym = st.session_state.get("currency_symbol", "₹")
    p = float(totals.get("sum_principal", 0))
    i = float(totals.get("sum_interest", 0))
    pen = float(totals.get("sum_penalty", 0))
    total = p + i + pen

    data_points = []
    if p > 0:   data_points.append({"name": "Principal", "value": p})
    if i > 0:   data_points.append({"name": "Interest",  "value": i})
    if pen > 0: data_points.append({"name": "Penalty",   "value": pen})

    center_amount_text = f"{sym}{fmt_inr_indian_grouping(total, 0)}"
    center_caption = title_note or "Total Default"

    options = {
        "color": [THEME_PALETTE["brand2"], THEME_PALETTE["success"], THEME_PALETTE["danger"]],
        "animationDuration": 800,
        "animationEasing": "cubicOut",
        "tooltip": {
            "trigger": "item",
            "formatter": f"{{{{b}}}}<br/>{sym}{{{{c}}}}<br/>{{{{d}}}}%"
        },
        "legend": {"orient": "horizontal", "bottom": 0,
                   "textStyle": {"color": THEME_PALETTE["title"], "fontSize": 12}},
        "series": [{
            "name": "Default Mix",
            "type": "pie",
            "radius": ["45%", "70%"],
            "center": ["50%", "50%"],
            "stillShowZeroSum": True,
            "minAngle": 1.5,
            "itemStyle": {"borderRadius": 8, "borderColor": "#ffffff", "borderWidth": 2},
            "label": {"show": True, "formatter": f"{{{{b}}}}\\n{sym}{{{{c}}}} ({{{{d}}}}%)", "fontSize": 15,
                      "lineHeight": 16, "color": THEME_PALETTE["value"]},
            "emphasis": {"scale": True, "scaleSize": 3,
                         "itemStyle": {"shadowBlur": 12, "shadowOffsetX": 0, "shadowColor": "rgba(0,0,0,0.25)"}},
            "data": data_points
        }],
        "graphic": [{
            "type": "group", "left": "center", "top": "45%", "z": 100,
            "children": [
                {"type": "text", "style": {"text": center_amount_text, "textAlign": "center",
                                           "fontSize": 16, "fontWeight": 700, "fill": THEME_PALETTE["value"]}},
                {"type": "text", "top": 28, "style": {"text": center_caption, "textAlign": "center",
                                                      "fontSize": 11, "fill": THEME_PALETTE["muted"]}}
            ]
        }]
    }
    st_echarts(options=options, height=360, key="default_mix_donut_echarts")


# ======================
# UI (REARRANGED)
# ======================
def defaulter_report():
    inject_theme_css()

    CURRENCY_CODE, CURRENCY_NAME, CURRENCY_SYMBOL = _currency_ctx()
    st.session_state["currency_code"] = CURRENCY_CODE
    st.session_state["currency_name"] = CURRENCY_NAME
    st.session_state["currency_symbol"] = CURRENCY_SYMBOL

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

    # Form
    with st.form("defaulter_form", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns([0.3, 1.1, 0.7, 0.7])

        with c1:
            st.markdown(
                """
                <div style="display:flex; align-items:center; gap:8px;">
                    <label style="font-size:18px; font-weight:700; margin-bottom:0;">As-of Date</label>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with c2:
            if "defaulter_as_of" not in st.session_state:
                st.session_state["defaulter_as_of"] = date.today()
            as_of_date = st.date_input(
                "",
                value=st.session_state["defaulter_as_of"],
                key="as_of_date_input",
                label_visibility="collapsed",
                help="Select the date for which to generate the defaulter report"
            )

        with c3:
            submitted = st.form_submit_button("Show Report", use_container_width=True)

        with c4:
            close_clicked = st.form_submit_button("Close", use_container_width=True)


    if close_clicked:
        try:
            st.switch_page("pages/Reports.py")
        except Exception:
            pass

    if not submitted:
        st.info(" Pick an As-of date and click **Show Report**.")
        return

    st.session_state["defaulter_as_of"] = as_of_date
    as_of_str = pd.to_datetime(as_of_date).strftime("%Y-%m-%d")

    # Compute + Filter
    with st.spinner("Computing from Parquet (DuckDB)…"):
        loans_all = compute_loan_frame(as_of_str)
        # Use status-only OR the smarter age-gate fallback; choose one:
        # defaulters = filter_defaulters(loans_all, as_of_str, age_gate=AGE_GATE_DAYS)
        defaulters = loans_all.loc[
            loans_all[LOAN_COLS["status_90"]].astype(str).str.upper() == "DEFAULTER"
        ].copy()

    if loans_all.empty:
        st.info(f"No loans found up to {as_of_str}.")
        return

    # KPIs
    kpis = kpis_from_df(loans_all, defaulters, as_of_str)
    totals = totals_from_df(defaulters)

    c1, c2, c3, c4 = st.columns(4)
    with c1: stat_card("Active Loans",  f"{kpis['active_loans']:,}",  "theme-success")
    with c2: stat_card("Total Loans",   f"{kpis['total_loans']:,}",   "theme-brand")
    with c3: stat_card("Defaulters",    f"{kpis['defaulters']:,}",    "theme-warning")
    with c4: stat_card("Closed Loans",  f"{kpis['closed_loans']:,}",  "theme-indigo")

    d1, d2, d3, d4 = st.columns(4)
    sym = st.session_state.get("currency_symbol", "₹")
    with d1: stat_card("Default Principal Balance", _fmt_money(totals["sum_principal"], sym), "theme-cyan")
    with d2: stat_card("Default Interest Balance",  _fmt_money(totals["sum_interest"],  sym), "theme-success")
    with d3: stat_card("Default Penalty Balance",   _fmt_money(totals["sum_penalty"],   sym), "theme-danger")
    with d4: stat_card("Total Default Outstanding", _fmt_money(totals["sum_total"],     sym), "theme-brand")


    st.markdown('<div style="border-top: 3px solid #000000; margin: 20px 0; width: 100%;"></div>', unsafe_allow_html=True)

    # Charts
    col_left, col_right = st.columns(2)
    with col_left:
        plot_status_donut_echarts(kpis, center_note=f"As of {as_of_str}")
    with col_right:
        plot_default_composition_pie_echarts(totals, title_note=f"As of {as_of_str}")

    st.markdown('<div style="border-top: 3px solid #000000; margin: 20px 0; width: 100%;"></div>', unsafe_allow_html=True)

    # Table
    defaulters_disp = defaulters.rename(columns={
        LOAN_COLS["loan"]:  "Loan number",
        LOAN_COLS["date"]:  "Date",
        LOAN_COLS["name"]:  "Name",
        LOAN_COLS["amt"]:   "Loan amount",
        LOAN_COLS["region"]:"Region",
        LOAN_COLS["pen_bal"]:"Penalty balance",
        LOAN_COLS["p_bal"]:"Principal balance",
        LOAN_COLS["out_90"]:"Total balance",
    }).copy()

    i_balance = (defaulters[LOAN_COLS["i_accr"]] - defaulters[LOAN_COLS["i_paid"]]).clip(lower=0)
    defaulters_disp["Interest balance"] = i_balance.values

    table_cols = [
        "Loan number","Date","Name","Loan amount","Region",
        "Penalty balance","Interest balance","Principal balance","Total balance"
    ]
    for c in ["Loan amount","Penalty balance","Interest balance","Principal balance","Total balance"]:
        defaulters_disp[c] = pd.to_numeric(defaulters_disp[c], errors="coerce").fillna(0.0).round(2)

    st.dataframe(defaulters_disp[table_cols], use_container_width=True, height=260)

    st.markdown('<div style="border-top: 3px solid #000000; margin: 20px 0; width: 100%;"></div>', unsafe_allow_html=True)

    # Downloads
    # --- Download Buttons Row ---
    col_a, col_b = st.columns([1, 1])  # equal width side by side

    with col_a:
        capture_script = """
        <style>
        .download-btn {
            background: #22c55e; color: white; padding: 10px 20px;
            border: none; border-radius: 25px; font-size: 14px;
            font-weight: 600; cursor: pointer;
            box-shadow: 0 4px 8px rgba(0,0,0,0.25);
            transition: all 0.2s ease;
        }
        .download-btn:hover { background: #16a34a; transform: translateY(-2px); }
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
        <button class="download-btn" onclick="downloadImage()">📸 Download Dashboard</button>
        """
        st.components.v1.html(capture_script, height=70)

    with col_b:
        def to_excel(df_):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_.to_excel(writer, index=False, sheet_name="Sheet1")
            return output.getvalue()

        excel_file = to_excel(defaulters_disp[table_cols])
        st.download_button(
            label="📥 Download Table",
            data=excel_file,
            file_name=f"defaulter_table_asof_{as_of_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
