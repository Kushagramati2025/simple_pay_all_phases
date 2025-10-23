from __future__ import annotations
import calendar
from datetime import date
# from dataclasses import dataclass   # unused
# from pathlib import Path            # unused

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from streamlit_echarts import st_echarts

from simple_pay.service.helper import get_selected_currency_code, get_currency_name_by_code
from Calculation.loan_duckdb import compute_all_38_duckdb

# =========================
#        SETTINGS
# =========================

# --- DB engine (only used for optional membership income until you move it to parquet) ---
DB_USER = "root"; DB_PWD = ""; DB_HOST = "localhost"; DB_PORT = 3306; DB_NAME = "keny"
CONN_STR = f"mysql+pymysql://{DB_USER}:{DB_PWD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
engine = create_engine(CONN_STR, pool_pre_ping=True, pool_size=10, max_overflow=20)

# --- Parquet / DuckDB inputs ---
from tools.config_paths import PARQUET_ROOT, DISB_GLOB, RECV_GLOB
DISB_SUBDIR  = "disbursement"  # keep: function signature still needs names
RECV_SUBDIR  = "receipt"
CFG_PATH     = "config/loan_rules.json"   # optional JSON to override rules

# --- Toggle: use MySQL for membership income (until you have a parquet for members) ---

@st.cache_data(ttl=300, show_spinner=False)
def _membership_sum_duck(year: int, month: int) -> float:
    import duckdb
    con = duckdb.connect()
    try:
        # Peek a single row to learn columns
        cols_df = con.execute(f"SELECT * FROM read_parquet('{RECV_GLOB}') LIMIT 1").fetchdf()
        cols = {c.lower(): c for c in cols_df.columns}  # map lower->original

        # Candidate columns
        date_candidates = ["receipt_date","txn_date","date","transaction_date","posting_date"]
        amt_candidates  = ["membership_income","membership_fee","membership"]
        tag_candidates  = ["fee_type","purpose","narration","remarks","description","category"]
        rcv_amt_candidates = ["amount_received","amount","receipt_amount","credit","value"]

        date_col = next((cols[c] for c in map(str.lower, date_candidates) if c in cols), None)
        amt_col  = next((cols[c] for c in map(str.lower, amt_candidates)  if c in cols), None)
        tag_col  = next((cols[c] for c in map(str.lower, tag_candidates)  if c in cols), None)
        rcv_col  = next((cols[c] for c in map(str.lower, rcv_amt_candidates) if c in cols), None)

        if date_col is None:
            return 0.0

        # Robust date expression: try native cast, then common string formats
        dexpr = f"""
            COALESCE(
                TRY_CAST({date_col} AS DATE),
                try_strptime({date_col}, '%Y-%m-%d'),
                try_strptime({date_col}, '%d/%m/%Y'),
                try_strptime({date_col}, '%d-%m-%Y')
            )
        """

        # Strategy A: explicit membership amount column
        if amt_col is not None:
            sql = f"""
                SELECT COALESCE(SUM(CAST({amt_col} AS DOUBLE)), 0) AS total
                FROM read_parquet('{RECV_GLOB}')
                WHERE YEAR({dexpr}) = {year} AND MONTH({dexpr}) = {month}
            """
            val = con.execute(sql).fetchone()[0] or 0.0
            if float(val) != 0.0:
                return float(val)

        # Strategy B: tagged membership lines, sum the receipt amount
        if tag_col is not None and rcv_col is not None:
            sql = f"""
                SELECT COALESCE(SUM(CAST({rcv_col} AS DOUBLE)), 0) AS total
                FROM read_parquet('{RECV_GLOB}')
                WHERE YEAR({dexpr}) = {year} AND MONTH({dexpr}) = {month}
                  AND LOWER(COALESCE({tag_col}, '')) LIKE '%%member%%'
            """
            val = con.execute(sql).fetchone()[0] or 0.0
            if float(val) != 0.0:
                return float(val)

        # Strategy C: fallback to members/*.parquet
        try:
            mglob = (PARQUET_ROOT / "members/*.parquet").as_posix()
            mem_cols_df = con.execute(f"SELECT * FROM read_parquet('{mglob}') LIMIT 1").fetchdf()
            mcols = {c.lower(): c for c in mem_cols_df.columns}
            m_amt  = next((mcols[c] for c in ["membership_income","membership_fee","membership"] if c in mcols), None)
            m_date = next((mcols[c] for c in ["receipt_date","txn_date","date","disb_date"] if c in mcols), None)
            if m_amt and m_date:
                mdexpr = f"""
                    COALESCE(
                        TRY_CAST({m_date} AS DATE),
                        try_strptime({m_date}, '%Y-%m-%d'),
                        try_strptime({m_date}, '%d/%m/%Y'),
                        try_strptime({m_date}, '%d-%m-%Y')
                    )
                """
                sql = f"""
                    SELECT COALESCE(SUM(CAST({m_amt} AS DOUBLE)), 0)
                    FROM read_parquet('{mglob}')
                    WHERE YEAR({mdexpr}) = {year} AND MONTH({mdexpr}) = {month}
                """
                val = con.execute(sql).fetchone()[0] or 0.0
                return float(val)
        except Exception:
            pass

        return 0.0
    finally:
        con.close()

# =========================
#        THEME / HELPERS
# =========================
PALETTE = {
    "brand": "#1f6feb",
    "brand2": "#0ea5e9",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "indigo": "#7c3aed",
    "surface": "#ffffff",
    "surface2": "#fbfdff",
    "title": "#6b7280",
    "value": "#0f172a",
    "muted": "#64748b",
    "border_rgba": "rgba(30, 65, 103, 0.12)",
}

def fmt_inr(n, decimals: int = 2) -> str:
    """Format number in Indian grouping, e.g. 123456789 -> 12,34,56,789.00"""
    try:
        x = float(n)
    except Exception:
        return f"{0:.{decimals}f}"
    neg = x < 0
    x = abs(x)
    s = f"{x:.{decimals}f}"
    i, d = s.split(".")
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
    return ("-" if neg else "") + grouped + "." + d

def echarts_colors():
    return [PALETTE["brand"], PALETTE["success"], PALETTE["warning"],
            PALETTE["danger"], PALETTE["indigo"], PALETTE["brand2"]]

def echarts_textStyle():
    return {"color": PALETTE["title"], "fontSize": 12}

def echarts_legend():
    return {"orient": "horizontal", "bottom": 0, "itemGap": 16, "textStyle": echarts_textStyle()}

def echarts_card_pie_base():
    return {
        "color": echarts_colors(),
        "animationDuration": 800,
        "animationEasing": "cubicOut",
        "tooltip": {"trigger": "item"},
        "legend": echarts_legend(),
        "series": [{
            "type": "pie",
            "radius": ["45%", "70%"],
            "center": ["50%", "50%"],
            "stillShowZeroSum": True,
            "clockwise": True,
            "itemStyle": {"borderRadius": 8, "borderColor": "#ffffff", "borderWidth": 2},
            "label": {"show": True, "fontSize": 14, "color": PALETTE["value"]},
            "emphasis": {"scale": True, "scaleSize": 3}
        }]
    }

# =========================
#          CSS
# =========================
def set_custom_style():
    st.markdown(f"""
    <style>
    :root {{
        --brand:{PALETTE['brand']}; --brand-2:{PALETTE['brand2']};
        --success:{PALETTE['success']}; --warning:{PALETTE['warning']};
        --danger:{PALETTE['danger']}; --indigo:{PALETTE['indigo']};
        --surface:{PALETTE['surface']}; --surface-2:{PALETTE['surface2']};
        --border:{PALETTE['border_rgba']};
        --title:{PALETTE['title']}; --value:{PALETTE['value']};
        --shadow:0 6px 14px rgba(18,38,63,0.06);
        --shadow-hover:0 10px 22px rgba(18,38,63,0.10);
    }}

    .stat-card {{
        background:linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%);
        border-radius:14px; padding:14px 16px;
        box-shadow:var(--shadow); border:1px solid var(--border);
        display:flex; flex-direction:column; justify-content:center;
        min-height:96px; transition:transform .14s ease, box-shadow .14s ease, border-color .14s ease;
        font-family:"Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        text-align:left; position:relative; overflow:hidden; isolation:isolate;
    }}
    .stat-card:hover {{ transform:translateY(-3px); box-shadow:var(--shadow-hover); }}
    .stat-card::before {{ content:""; position:absolute; inset:0 0 auto 0; height:3px; background:var(--accent, var(--brand)); opacity:.9; z-index:1; }}
    .stat-title {{ font-size:22px; color:var(--title); font-weight:700; margin:2px 0 4px 0; line-height:1.2; letter-spacing:.2px; }}
    .stat-value {{ font-size:22px; font-weight:700; color:var(--value); margin:0; line-height:1.15; }}

    .theme-brand  {{ --accent:var(--brand);  }}
    .theme-cyan   {{ --accent:var(--brand-2);}}
    .theme-success{{ --accent:var(--success);}}
    .theme-warning{{ --accent:var(--warning);}}
    .theme-danger {{ --accent:var(--danger); }}
    .theme-indigo {{ --accent:var(--indigo); }}

    .section-title {{ font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; color:var(--title); margin:16px 2px 8px; }}
    .totals-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:10px; }}
    .total-card {{
        position:relative; background:linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%);
        border-radius:14px; padding:12px 14px; box-shadow:var(--shadow); border:1px solid var(--border);
        min-height:64px; display:grid; grid-template-columns:1fr auto; align-items:center;
    }}
    .total-card::before {{ content:""; position:absolute; inset:0 0 auto 0; height:3px; background:var(--accent, var(--brand)); opacity:.9; }}
    .total-label {{ font-size:13px; color:var(--title); font-weight:700; }}
    .total-value {{ font-weight:800; font-size:15px; color:var(--value); }}

    div[data-testid^="stDateInput"], div[data-testid*="date_input"]{{margin-bottom:0!important;padding-bottom:0!important;}}
    div[data-testid^="stHorizontalBlock"]{{margin-top:0!important;padding-top:0!important;}}
    div[data-testid^="stVerticalBlock"]>div[data-testid^="stHorizontalBlock"]{{margin-top:0!important;padding-top:0!important;}}
    [data-testid="stMetric"],[data-testid="stCard"],.stMetric,.stCard{{margin-top:0!important;margin-bottom:0!important;padding-top:0!important;padding-bottom:0!important;}}
    @media (min-width:1000px){{ .stat-card, .total-card{{ margin:4px!important; }} }}
    @media (max-width:520px){{ .total-card{{ grid-template-columns:1fr; row-gap:6px; }} .total-value{{ justify-self:start; }} }}
    </style>
    """, unsafe_allow_html=True)


# =========================
#     Top-right close
# =========================
def add_top_right_close_button(offset_top: int = 120, target_page: str = "pages/Reports.py"):
    st.markdown(f"""
        <style>
        .top-right-btn {{
            position: fixed;
            top: {offset_top}px;
            right: 12px;
            z-index: 99999;
        }}
        .top-right-btn button {{
            width: 36px; height: 36px;
            border-radius: 999px;
            background: #111827; color: #fff;
            border: 1px solid rgba(17,24,39,.15);
            font-weight: 800; font-size: 18px;
            box-shadow: 0 6px 14px rgba(18,38,63,.18);
            cursor: pointer;
        }}
        .top-right-btn button:hover {{ background: #272f3c; }}
        </style>
        <div class="top-right-btn">
    """, unsafe_allow_html=True)

    if st.button("Close", key="go_reports_btn", help="Go to Reports"):
        st.switch_page(target_page)

    st.markdown("</div>", unsafe_allow_html=True)

@st.cache_data(ttl=60)
def get_currency_symbol_by_code(code: str) -> str | None:
    if not code:
        return None
    try:
        with engine.connect() as conn:
            # Try common column names for symbol in your `currency` table
            for col in ("symbol", "symbol_prefix", "symbol_char"):
                try:
                    q = f"SELECT {col} FROM currency WHERE code=:code LIMIT 1"
                    row = pd.read_sql(text(q), conn, params={"code": code}).iloc[0]
                    if row[0]:
                        return str(row[0])
                except Exception:
                    continue
    except Exception:
        pass
    return None

def _currency_ctx():
    """Return (CODE, NAME, SYMBOL) from DB with sensible fallbacks."""
    code = (get_selected_currency_code() or "INR").upper()
    name = get_currency_name_by_code(code) or code
    symbol = get_currency_symbol_by_code(code) or ("₹" if code == "INR" else code + " ")
    return code, name, symbol

def _fmt_money(n: float, symbol: str | None = None, decimals: int = 2) -> str:
    # Uses Indian grouping via fmt_inr() but with your dynamic symbol
    try:
        if symbol is None:
            symbol = st.session_state.get("currency_symbol", "₹")
        return f"{symbol}{fmt_inr(n, decimals)}"
    except Exception:
        symbol = symbol or st.session_state.get("currency_symbol", "₹")
        return f"{symbol}{fmt_inr(0.0, decimals)}"

# =========================
#     Month/Year UI
# =========================
def eom(d: date) -> date:
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=last)

import duckdb

def get_data_date_bounds():
    con = duckdb.connect()
    try:
        q = f"""
        SELECT MIN(CAST(disb_date AS DATE)) AS dmin,
               MAX(CAST(disb_date AS DATE)) AS dmax
        FROM read_parquet('{DISB_GLOB}')
        """
        dmin, dmax = con.execute(q).fetchone()
    finally:
        con.close()

    if dmin is None or dmax is None:
        today = date.today()
        return today, today
    return dmin, dmax

def month_year_selector_flat(
    form_key: str = "month_year_flat",
    bounds: tuple[date, date] | None = None,
    session_prefix: str = "closed_loans",
    close_target_page: str = "pages/Reports.py",
) -> tuple[date | None, date | None, bool]:
    import calendar

    set_custom_style()
    st.markdown("""
        <style>
        /* Hide Streamlit header + toolbars across versions */
        header[data-testid="stHeader"] { display:none !important; }
        div[data-testid="stToolbar"] { display:none !important; }
        div[data-testid="stDecoration"] { display:none !important; }   /* Deploy/Viewer badge */
        div[data-testid="stStatusWidget"] { display:none !important; }  /* Alt badge location */

        /* Old IDs (still present on some versions) */
        #MainMenu { visibility:hidden; }
        footer { visibility:hidden; }

        /* Extra fallbacks some skins use */
        div[data-testid="collapsedControl"] { display:none !important; }      /* top-right kebab */
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] { 
            display:none !important; 
        }

        /* Tighten padding */
        .block-container{
            padding-top:1rem !important;
            padding-bottom:1rem !important;
        }
        </style>
    """, unsafe_allow_html=True)


    # ---- Data bounds ----
    if bounds and all(bounds):
        data_min, data_max = bounds
    else:
        data_min, data_max = get_data_date_bounds()

    years = list(range(data_max.year, data_min.year - 1, -1))
    months = [
        (1, "January"), (2, "February"), (3, "March"), (4, "April"),
        (5, "May"), (6, "June"), (7, "July"), (8, "August"),
        (9, "September"), (10, "October"), (11, "November"), (12, "December")
    ]

    sel_year_key = f"{session_prefix}_year"
    sel_month_key = f"{session_prefix}_month"
    if sel_year_key not in st.session_state:
        st.session_state[sel_year_key] = data_max.year
    if sel_month_key not in st.session_state:
        st.session_state[sel_month_key] = data_max.month

    submitted = False
    with st.form(form_key, clear_on_submit=False):
        # label, input, label, input, show, close
        c1, c2, c3, c4, c5, c6 = st.columns([0.35, 1.2, 0.35, 0.9, 0.7, 0.7])

        # --- Month label (tight to select) ---
        with c1:
            st.markdown(
                "<label style='font-size:18px; font-weight:800; margin:0; display:flex; align-items:center;'>Month</label>",
                unsafe_allow_html=True
            )

        # --- Month select ---
        with c2:
            month_names = [nm for _, nm in months]
            m_idx = [i for i, (num, _) in enumerate(months)
                    if num == st.session_state[sel_month_key]][0]
            sel_month_name = st.selectbox(
                "", month_names, index=m_idx,
                key=f"{session_prefix}_month_select",
                label_visibility="collapsed"
            )

        # --- Year label (tight to input) ---
        with c3:
            st.markdown(
                "<label style='font-size:18px; font-weight:800; margin:0; display:flex; align-items:center;'>Year</label>",
                unsafe_allow_html=True
            )

        # --- Year input ---
        with c4:
            default_y_txt = str(st.session_state[sel_year_key])
            year_text = st.text_input(
                "", value=default_y_txt,
                key=f"{session_prefix}_year_text",
                label_visibility="collapsed"
            )

        # --- Buttons ---
        with c5:
            show_clicked = st.form_submit_button("Show", use_container_width=True)
        with c6:
            close_clicked = st.form_submit_button("Close", use_container_width=True)

    # ---- Button logic ----
    if close_clicked:
        st.switch_page(close_target_page)
        return None, None, False

    if not show_clicked:
        return None, None, False

    # Parse values
    month_num = next(num for num, nm in months if nm == sel_month_name)
    try:
        year = int(str(year_text).strip())
    except Exception:
        year = st.session_state[sel_year_key]

    # Clamp year to bounds
    if years:
        year = max(min(year, max(years)), min(years))

    try:
        start_date = date(year, month_num, 1)
        end_date = date(year, month_num, calendar.monthrange(year, month_num)[1])
    except Exception:
        st.warning("Invalid month/year selection.")
        return None, None, False

    # Validate
    if start_date.replace(day=1) < data_min.replace(day=1) or start_date.replace(day=1) > data_max.replace(day=1):
        st.warning("Selected month is outside the available data range.")
        return None, None, False

    st.session_state[sel_year_key] = year
    st.session_state[sel_month_key] = month_num

    return start_date, end_date, True


# =========================
#      DATA LOADERS
# =========================
@st.cache_data(ttl=300, show_spinner=False)
def _load_month_df(start_date: date, end_date: date) -> pd.DataFrame:
    raw = compute_all_38_duckdb(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        parquet_root=PARQUET_ROOT,
        disb_subdir=DISB_SUBDIR,
        recv_subdir=RECV_SUBDIR,
        config_path=CFG_PATH,
    )
    return _adapt_month_df_for_metrics(raw)

USE_MYSQL_MEMBERSHIP = False  # <- set False

@st.cache_data(ttl=300, show_spinner=False)
def _membership_sum_mysql(year: int, month: int) -> float:
    # DuckDB version: replace MEMBERS_GLOB with your file/pattern
    MEMBERS_GLOB = (PARQUET_ROOT / "members/*.parquet").as_posix()
    con = duckdb.connect()
    try:
        sql = f"""
        SELECT COALESCE(SUM(CAST(membership_income AS DOUBLE)), 0)
        FROM read_parquet('{MEMBERS_GLOB}')
        WHERE YEAR(CAST(disb_date AS DATE)) = {year}
          AND MONTH(CAST(disb_date AS DATE)) = {month}
        """
        total = con.execute(sql).fetchone()[0] or 0.0
    finally:
        con.close()
    return float(total)

def _adapt_month_df_for_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Map new calculator columns to the old names used by the dashboard:
      - Loan Amount -> disb_amount
      - Total Interest Accrued -> Interest_accrued_30 + penalties (31–90)
      - Amount Repaid within a Month -> Amount_repaid_within_30_days
      - Total Amount Received (31–45) -> Amount_Received_within_31_to_45_days
      - Total Amount Received (46–60) -> Amount_Received_within_46_to_60_days
      - Total Amount Received (61–90) -> Amount_Received_within_61_to_90_days
    """
    if df.empty:
        cols = [
            "Loan Amount", "Total Interest Accrued",
            "Amount Repaid within a Month",
            "Total Amount Received (31–45)",
            "Total Amount Received (46–60)",
            "Total Amount Received (61–90)",
        ]
        for c in cols:
            if c not in df.columns:
                df[c] = 0.0
        return df

    # Ensure presence of the new names (fill if missing)
    req = [
        "disb_amount",
        "Interest_accrued_30",
        "Penalty_31_45", "Penalty_46_60", "Penalty_61_90",
        "Amount_repaid_within_30_days",
        "Amount_Received_within_31_to_45_days",
        "Amount_Received_within_46_to_60_days",
        "Amount_Received_within_61_to_90_days",
    ]
    for c in req:
        if c not in df.columns:
            df[c] = 0.0

    penalties_total = (
        df["Penalty_31_45"].fillna(0)
        + df["Penalty_46_60"].fillna(0)
        + df["Penalty_61_90"].fillna(0)
    )
    total_interest_accrued = df["Interest_accrued_30"].fillna(0) + penalties_total

    out = df.copy()
    out["Loan Amount"] = out["disb_amount"].fillna(0)
    out["Total Interest Accrued"] = total_interest_accrued

    out["Amount Repaid within a Month"]  = out["Amount_repaid_within_30_days"].fillna(0)
    out["Total Amount Received (31–45)"] = out["Amount_Received_within_31_to_45_days"].fillna(0)
    out["Total Amount Received (46–60)"] = out["Amount_Received_within_46_to_60_days"].fillna(0)
    out["Total Amount Received (61–90)"] = out["Amount_Received_within_61_to_90_days"].fillna(0)
    return out

# =========================
#        HELPERS
# =========================
def _inr(n: float) -> str:
    return _fmt_money(n)   # uses session symbol + Indian grouping


def _month_window(year: int, month: int) -> tuple[date, date]:
    start_dt = date(year, month, 1)
    end_dt   = date(year, month, calendar.monthrange(year, month)[1])
    return start_dt, end_dt


# =========================
#   KPI Dashboard (DuckDB)
# =========================
def monthly_kpi_dashboard(year: int, month: int, show_header: bool = True):
    start_dt, end_dt = _month_window(year, month)
    df = _load_month_df(start_dt, end_dt)

    # Core metrics from your computed columns
    principal_sum    = float(df["Loan Amount"].fillna(0).sum())
    interest_sum     = float(df["Total Interest Accrued"].fillna(0).sum())
    total_receivable = principal_sum + interest_sum

    # Receipts within 0–90 days window (consistent with calculator)
    total_received = float(
        df["Amount Repaid within a Month"].fillna(0).sum()
      + df["Total Amount Received (31–45)"].fillna(0).sum()
      + df["Total Amount Received (46–60)"].fillna(0).sum()
      + df["Total Amount Received (61–90)"].fillna(0).sum()
    )

    # Membership (MySQL fallback; switch off with USE_MYSQL_MEMBERSHIP=False)
    # always compute from parquet (DuckDB)
    membership_sum = _membership_sum_mysql(year, month)   # reads local_cache/members/*.parquet



    # Optional: Surplus & Total Income definitions
    # Here we align with your older KPI semantics:
    #   Surplus Collected ≈ Received (0–90 window) - Disbursed (month)
    surplus_sum = max(0.0, total_received - principal_sum)
    total_income = surplus_sum + membership_sum

    remaining = max(0.0, total_receivable - total_received)

    if show_header:
        st.markdown(f"### KPIs — {date(year, month, 1):%B %Y}")

    r1 = st.columns(4)
    with r1[0]: _kpi_card("Principal Disbursed",  _inr(principal_sum),    "theme-brand")
    with r1[1]: _kpi_card("Interest Receivable",  _inr(interest_sum),     "theme-cyan")
    with r1[2]: _kpi_card("Total Receivable",     _inr(total_receivable), "theme-indigo")
    with r1[3]: _kpi_card("Remaining",            _inr(remaining),        "theme-warning")

    r2 = st.columns(4)
    with r2[0]: _kpi_card("Total Received (0–90d)", _inr(total_received),   "theme-success")
    with r2[1]: _kpi_card("Surplus Collected",      _inr(surplus_sum),      "theme-danger")
    with r2[2]: _kpi_card("Membership Income",      _inr(membership_sum),   "theme-brand")
    with r2[3]: _kpi_card("Total Income",           _inr(total_income),     "theme-indigo")


def _kpi_card(title: str, value: str, theme: str = "theme-brand"):
    st.markdown(
        f"""
        <div class="stat-card {theme}">
            <div class="stat-title">{title}</div>
            <div class="stat-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True
    )


# =========================
#   Example page usage
# =========================
def render_page():
    # 1) Do this once, first, before any other st.* calls on this page
    st.set_page_config(layout="wide")

    # 2) Hide Streamlit header/toolbar + tighten padding (page-only)
    st.markdown("""
        <style>
        /* Hide Streamlit header + toolbars across versions */
        header[data-testid="stHeader"] { display:none !important; }
        div[data-testid="stToolbar"] { display:none !important; }
        div[data-testid="stDecoration"] { display:none !important; }   /* Deploy/Viewer badge */
        div[data-testid="stStatusWidget"] { display:none !important; }  /* Alt badge location */

        /* Old IDs (still present on some versions) */
        #MainMenu { visibility:hidden; }
        footer { visibility:hidden; }

        /* Extra fallbacks some skins use */
        div[data-testid="collapsedControl"] { display:none !important; }      /* top-right kebab */
        section[data-testid="stSidebar"] [data-testid="stSidebarHeader"] { 
            display:none !important; 
        }

        /* Tighten padding */
        .block-container{
            padding-top:1rem !important;
            padding-bottom:1rem !important;
        }
        </style>
    """, unsafe_allow_html=True)



    # 3) Your theme/styles
    set_custom_style()

    # 4) Currency context
    CURRENCY_CODE, CURRENCY_NAME, CURRENCY_SYMBOL = _currency_ctx()
    st.session_state["currency_code"] = CURRENCY_CODE
    st.session_state["currency_name"] = CURRENCY_NAME
    st.session_state["currency_symbol"] = CURRENCY_SYMBOL

    # 5) Layout
    c_left, c_right = st.columns([1, 0.12])

    with c_left:
        start_date, end_date, ok = month_year_selector_flat(form_key="month_year_flat__page")

    with c_right:
        st.markdown("<div style='display:flex;justify-content:flex-end;'>", unsafe_allow_html=True)
        add_top_right_close_button(offset_top=0, target_page="pages/Reports.py")
        st.markdown("</div>", unsafe_allow_html=True)

    if not ok or not start_date:
        st.info("Pick Month & Year and click **Show**.")
        return

    y, m = start_date.year, start_date.month

    with st.expander(" Troubleshoot membership (click to open)"):
        debug_membership_panel(y, m)

    st.markdown(f"## Monthly Report — {start_date:%B %Y}")
    monthly_kpi_dashboard(y, m)

    chart_cashflow_bridge_horizontal(y, m)

    c1, c2 = st.columns(2)
    with c1:
        chart_efficiency_gauge(y, m)
    with c2:
        chart_income_composition_donut(y, m)


# =========================
#   Chart Helpers (data)
# =========================
def _get_month_metrics(year: int, month: int) -> dict:
    start_dt, end_dt = _month_window(year, month)
    df = _load_month_df(start_dt, end_dt)

    principal_sum    = float(df["Loan Amount"].fillna(0).sum())
    interest_sum     = float(df["Total Interest Accrued"].fillna(0).sum())
    receivable_sum   = principal_sum + interest_sum

    received_sum = float(
        df["Amount Repaid within a Month"].fillna(0).sum()
      + df["Total Amount Received (31–45)"].fillna(0).sum()
      + df["Total Amount Received (46–60)"].fillna(0).sum()
      + df["Total Amount Received (61–90)"].fillna(0).sum()
    )

    membership_sum = _membership_sum_mysql(year, month)   # reads local_cache/members/*.parquet



    disb_sum = principal_sum
    net_surplus = (-disb_sum) + interest_sum + received_sum + membership_sum

    return dict(
        principal=principal_sum,
        interest=interest_sum,
        receivable=receivable_sum,
        received=received_sum,
        membership=membership_sum,
        disbursed=disb_sum,
        net=net_surplus,
    )


# =========================
#   1) Cash-Flow Bridge
# =========================
def chart_cashflow_bridge_horizontal(year: int, month: int):
    m = _get_month_metrics(year, month)
    symbol = st.session_state.get("currency_symbol", "₹")


    steps = ["Disbursed", "Interest", "Receipts", "Membership", "Net"]

    vals_raw = [
        -m["disbursed"],  # outflow
        m["interest"],
        m["received"],
        m["membership"],
        (-m["disbursed"]) + m["interest"] + m["received"] + m["membership"],
    ]

    # No scaling: keep raw numbers
    vals = vals_raw


    base, cum = [], 0.0
    for label, v in zip(steps, vals):
        base.append(0.0 if label == "Net" else cum)
        if label != "Net":
            cum += v

    color_map = {
        "Disbursed": PALETTE["danger"],
        "Interest":  PALETTE["indigo"],
        "Receipts":  PALETTE["success"],
        "Membership": PALETTE["brand2"],
        "Net":       PALETTE["muted"],
    }

    # preformatted labels + simple tooltips (no JS formatters)
    value_items = []
    for step, v_raw, v_scaled in zip(steps, vals_raw, vals):
        label_txt = f"{symbol}{fmt_inr(abs(v_raw))}" if step != "Net" else f"{symbol}{fmt_inr(v_raw)}"
        tip_txt   = (
            f"<b>{step}</b><br/>{symbol}{fmt_inr(v_raw)}"
        )


        
        value_items.append({
            "value": round(v_scaled, 2),
            "label": {"show": True, "position": "right", "formatter": label_txt},
            "tooltip": {"formatter": tip_txt},
            "itemStyle": {"color": color_map.get(step, PALETTE["brand"]), "borderRadius": [4, 4, 4, 4]},
        })

    options = {
        "title": {"text": f"Cash Flow Bridge — {date(year, month, 1):%b %Y}", "left": 6, "textStyle": echarts_textStyle()},
        "animationDuration": 600,
        "tooltip": {"trigger": "item"},
        "grid": {"left": 8, "right": 16, "top": 40, "bottom": 16, "containLabel": True},
        "xAxis": {
        "type": "value",
        "name": f"{symbol}",

  
            "axisLabel": {"formatter": "{value}", "color": PALETTE["title"]},
            "splitLine": {"lineStyle": {"type": "dashed", "color": PALETTE["border_rgba"]}},
        },
        "yAxis": {"type": "category", "data": steps, "axisLabel": {"color": PALETTE["title"], "margin": 12}},
        "series": [
            {
                "name": "helper",
                "type": "bar",
                "stack": "total",
                "itemStyle": {"borderColor": "transparent", "color": "transparent"},
                "emphasis": {"disabled": True},
                "data": base,
                "barWidth": 22
            },
            {
                "name": "value",
                "type": "bar",
                "stack": "total",
                "data": value_items,
                "barWidth": 22,
                "barMinHeight": 6,   # <-- add this line
                "z": 3
            },

        ]
    }

    st_echarts(options=options, height="420px", key=f"cash_bridge_{year}_{month}")


# =========================
#   2) Efficiency Gauge
# =========================
def chart_efficiency_gauge(year: int, month: int):
    m = _get_month_metrics(year, month)
    denom = max(1e-9, m["receivable"])  # avoid div-by-zero
    eff = round((m["received"] / denom) * 100.0, 2)

    options = {
        "title": {"text": "Collection Efficiency", "left": 6, "textStyle": echarts_textStyle()},
        "tooltip": {"formatter": "function(p){return p.name + ': ' + p.value + '%';}"},
        "series": [{
            "type": "gauge",
            "startAngle": 210, "endAngle": -30, "min": 0, "max": 100, "splitNumber": 10,
            "axisLine": {
                "lineStyle": {
                    "width": 12,
                    "color": [
                        [0.70, "#ef4444"],   # <70% Red
                        [0.90, "#f59e0b"],   # 70–90% Yellow
                        [1.00, "#10b981"]    # >90% Green
                    ]
                }
            },
            "pointer": {"icon": "path://M2,0 L-2,0 L0,-40 Z", "length": "62%", "width": 6},
            "axisTick": {"show": False}, "splitLine": {"length": 10, "lineStyle": {"width": 1}},
            "axisLabel": {"distance": 10, "fontSize": 10},
            "detail": {"valueAnimation": True, "formatter": "{value}%", "fontSize": 20},
            "data": [{"value": eff, "name": "Efficiency"}]
        }]
    }
    st_echarts(options, height="320px", key=f"eff_gauge_{year}_{month}")


# =========================
#   3) Income Composition Donut
# =========================
def chart_income_composition_donut(year: int, month: int):
    symbol = st.session_state.get("currency_symbol", "₹")

    m = _get_month_metrics(year, month)
    data = [
        {"name": "Principal",  "value": max(m["principal"], 0.0)},
        {"name": "Interest",   "value": max(m["interest"],  0.0)},
        {"name": "Membership", "value": max(m["membership"], 0.0)},
    ]
    total = sum(d["value"] for d in data)
    total_str = f"{symbol}{fmt_inr(total)}"


    opts = echarts_card_pie_base()
    opts["title"] = {"text": "Income Composition", "left": "center", "textStyle": echarts_textStyle()}
    opts["tooltip"] = {
    "trigger": "item",
    "formatter": f"""
        function (p) {{
            const v = Number(p.value||0).toLocaleString('en-IN',{{minimumFractionDigits:2}});
            return `<b>${{p.name}}</b><br/>{symbol}${{v}} (${{p.percent}}%)`;
        }}
    """
}

    opts["legend"] = echarts_legend()
    opts["series"][0].update({
        "name": "Income Components",
        "radius": ["45%", "70%"],
        "label": {"show": True, "formatter": "{b}: {d}%"},
        "labelLine": {"show": True},
        "selectedMode": "single",
        "emphasis": {"scale": True, "scaleSize": 4},
        "data": data
    })
    # Center total label
    opts["graphic"] = [{
        "type": "group",
        "left": "center",
        "top": "middle",
        "children": [
            {"type": "text", "left": -16, "top": -8,
             "style": {"text": "Total", "fontSize": 12, "fill": PALETTE["title"], "fontWeight": 600}},
            {"type": "text", "left": -40, "top": 8,
             "style": {"text": total_str, "fontSize": 14, "fill": PALETTE["value"], "fontWeight": 800}}
        ]
    }]

    st_echarts(options=opts, height="320px", key=f"inc_donut_{year}_{month}")

def debug_membership_panel(y, m):
    import duckdb
    st.subheader("Debug: Membership Income")

    st.code(f"RECV_GLOB = {RECV_GLOB}", language="text")

    con = duckdb.connect()
    try:
        # Peek schema
        try:
            df_head = con.execute(f"SELECT * FROM read_parquet('{RECV_GLOB}') LIMIT 5").fetchdf()
        except Exception as e:
            st.error(f"Could not read RECV_GLOB: {e}")
            con.close()
            return

        st.write("**First 5 rows from receipts parquet(s):**")
        st.dataframe(df_head)

        cols = {c.lower(): c for c in df_head.columns}
        def pick(cands): return next((cols[c] for c in cands if c in cols), None)

        date_col = pick(["receipt_date","txn_date","date","transaction_date","posting_date"])
        tag_col  = pick(["fee_type","purpose","narration","remarks","description","category"])
        amt_col  = pick(["amount_received","amount","receipt_amount","credit","value"])

        st.write("**Chosen columns**", {"date_col": date_col, "tag_col": tag_col, "amt_col": amt_col})

        if not date_col:
            st.error("No usable date column found in receipts.")
            return

        dexpr = f"""
        COALESCE(
            TRY_CAST({date_col} AS DATE),
            try_strptime({date_col}, '%Y-%m-%d'),
            try_strptime({date_col}, '%d/%m/%Y'),
            try_strptime({date_col}, '%d-%m-%Y')
        )
        """

        q_rows = f"""
        SELECT COUNT(*) AS rows_in_month,
               MIN({dexpr}) AS min_date_parsed,
               MAX({dexpr}) AS max_date_parsed
        FROM read_parquet('{RECV_GLOB}')
        WHERE YEAR({dexpr}) = {y} AND MONTH({dexpr}) = {m}
        """
        st.write("**Rows in selected month (after date parsing):**")
        st.dataframe(con.execute(q_rows).fetchdf())

        if tag_col:
            q_tags = f"""
            SELECT LOWER(TRIM({tag_col})) AS tag_val, COUNT(*) AS n
            FROM read_parquet('{RECV_GLOB}')
            WHERE YEAR({dexpr}) = {y} AND MONTH({dexpr}) = {m}
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 20
            """
            st.write("**Top tag values (this month):**")
            st.dataframe(con.execute(q_tags).fetchdf())
        else:
            st.info("No tag-like column found (fee_type/purpose/remarks/description/category).")

        if tag_col and amt_col:
            q_member = f"""
            SELECT SUM(CAST({amt_col} AS DOUBLE)) AS sum_amount,
                   COUNT(*) AS rows
            FROM read_parquet('{RECV_GLOB}')
            WHERE YEAR({dexpr}) = {y} AND MONTH({dexpr}) = {m}
              AND (
                LOWER(COALESCE({tag_col}, '')) LIKE '%member%' OR
                LOWER(COALESCE({tag_col}, '')) LIKE '%membership%'
              )
            """
            st.write("**Sum for rows tagged with 'member' (heuristic):**")
            st.dataframe(con.execute(q_member).fetchdf())
        else:
            st.info("Skipping 'member' sum because tag_col or amt_col was not found.")

        membership_like_cols = [c for c in df_head.columns if "member" in c.lower()]
        st.write("**Columns containing 'member' in their names:**", membership_like_cols or "(none)")
    finally:
        con.close()


# =========================
#   Print button (optional)
# =========================
def show_download_dashboard_button():
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
    button:hover {
        background: #16a34a;
        transform: translateY(-2px);
    }
    </style>
    <script>
    function downloadImage(){ window.parent.print() }
    </script>
    <button onclick="downloadImage()">📸 Download Dashboard</button>
    """
    st.components.v1.html(capture_script, height=200)



# ====== BRANCH LEADERBOARD (exported) ======
import numpy as np
import pandas as pd
from sqlalchemy import text

# Per-branch receivable (principal + interest_due by your rule) for the chosen month
SQL_BRANCH_RECEIVABLE_MONTH = """
WITH per_loan AS (
    SELECT 
        d.loan_id,
        d.branch,
        d.amount_disbursed,
        d.amount_disbursed *
        LEAST(
            0.14 + (GREATEST(AVG(DATEDIFF(r.receipt_date, d.disb_date)) - 14, 0) * 0.01),
            0.30
        ) AS interest_due
    FROM disbursement d
    LEFT JOIN receipt r ON d.loan_id = r.loan_id
    WHERE YEAR(d.disb_date) = :year
      AND MONTH(d.disb_date) = :month
    GROUP BY d.loan_id, d.branch, d.amount_disbursed
)
SELECT 
    branch,
    SUM(COALESCE(amount_disbursed,0) + COALESCE(interest_due,0)) AS receivable
FROM per_loan
GROUP BY branch
"""

# Per-branch receipts (calendar-month)
SQL_BRANCH_RECEIPTS_MONTH = """
SELECT d.branch, SUM(COALESCE(r.amount_received,0)) AS receipts
FROM receipt r
JOIN disbursement d ON d.loan_id = r.loan_id
WHERE YEAR(r.receipt_date) = :year AND MONTH(r.receipt_date) = :month
GROUP BY d.branch
"""

def _prev_year_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)

def _branch_month_df_duck(y: int, m: int) -> pd.DataFrame:
    # Use the same month window and the same calculator that feeds all KPIs
    start_dt, end_dt = _month_window(y, m)
    df = _load_month_df(start_dt, end_dt)  # already adapted names

    if df.empty:
        return pd.DataFrame(columns=["branch","receivable","receipts","efficiency"])

    # Expect the calculator to include 'branch' (if not, merge it in earlier)
    need_cols = ["branch",
                 "Loan Amount", "Total Interest Accrued",
                 "Amount Repaid within a Month",
                 "Total Amount Received (31–45)",
                 "Total Amount Received (46–60)",
                 "Total Amount Received (61–90)"]
    for c in need_cols:
        if c not in df.columns:
            df[c] = 0.0

    df["receivable"] = df["Loan Amount"].fillna(0) + df["Total Interest Accrued"].fillna(0)
    df["receipts"]   = (
        df["Amount Repaid within a Month"].fillna(0) +
        df["Total Amount Received (31–45)"].fillna(0) +
        df["Total Amount Received (46–60)"].fillna(0) +
        df["Total Amount Received (61–90)"].fillna(0)
    )

    g = df.groupby("branch", as_index=False).agg(
        receivable=("receivable", "sum"),
        receipts=("receipts", "sum"),
    )
    g["receivable"] = g["receivable"].clip(lower=0.0)
    g["receipts"]   = g["receipts"].clip(lower=0.0)
    g["efficiency"] = np.where(g["receivable"] > 0, g["receipts"] / g["receivable"], 0.0)
    return g

def _now_prev(y: int, m: int) -> pd.DataFrame:
    py, pm = _prev_year_month(y, m)
    cur = _branch_month_df_duck(y, m).rename(
        columns={"receivable": "recv_now", "receipts": "rcp_now", "efficiency": "eff_now"}
    )
    prv = _branch_month_df_duck(py, pm).rename(
        columns={"receivable": "recv_prev", "receipts": "rcp_prev", "efficiency": "eff_prev"}
    )[["branch", "recv_prev", "rcp_prev", "eff_prev"]]

    df = pd.merge(cur, prv, on="branch", how="left") \
           .fillna({"recv_prev": 0.0, "rcp_prev": 0.0, "eff_prev": 0.0})
    df["eff_pct"]       = df["eff_now"] * 100.0
    df["delta_eff_pp"]  = (df["eff_now"] - df["eff_prev"]) * 100.0
    df["delta_rcp_abs"] = df["rcp_now"] - df["rcp_prev"]
    df["delta_recv_abs"]= df["recv_now"] - df["recv_prev"]
    df["delta_rcp_pct"] = np.where(df["rcp_prev"] > 0, (df["rcp_now"] / df["rcp_prev"] - 1) * 100.0, np.nan)
    df["delta_recv_pct"]= np.where(df["recv_prev"] > 0, (df["recv_now"] / df["recv_prev"] - 1) * 100.0, np.nan)
    return df

def _fmt_inr(x):
    symbol = st.session_state.get("currency_symbol", "₹")
    try:
        return f"{symbol}{fmt_inr(float(x), 2)}"   # was 0
    except Exception:
        return f"{symbol}0"



def _value_label(metric_key, v, d):
    if metric_key in ("eff_pct","delta_eff_pp"):
        base = f"{v:.1f}%" if metric_key == "eff_pct" else f"{v:+.1f} pp"
        if d is None:
            return base
        arrow = "▲" if d > 0 else ("▼" if d < 0 else "•")
        return f"{base} ({arrow} {d:+.1f}{' pp' if metric_key=='eff_pct' else ''})"
    if metric_key in ("rcp_now","recv_now","delta_rcp_abs","delta_recv_abs"):
        base = _fmt_inr(v)
        if d is None:
            return base
        arrow = "▲" if d > 0 else ("▼" if d < 0 else "•")
        return f"{base} ({arrow} {_fmt_inr(d)})"
    if metric_key in ("delta_rcp_pct","delta_recv_pct"):
        return f"{v:+.1f}%"
    return f"{v:.2f}"

def _bar_items(names, values, deltas, metric_key):
    items = []
    for nm, v, d in zip(names, values, deltas):
        lab  = _value_label(metric_key, v, d)
        item = {"value": round(float(v), 2), "label": {"show": True, "position": "right", "formatter": lab}}
        if d is not None and not pd.isna(d):
            item["itemStyle"] = {"color": "#10b981" if d > 0 else ("#ef4444" if d < 0 else "#64748b")}
        items.append(item)
    return items

def build_branch_leaderboard_options(y: int, m: int, *,
    metric="efficiency", top_n=10, min_receivable=0.0,
    highlight_branch=None, titles=None, palette=None):

    df = _now_prev(y, m)   # <-- new DuckDB-only path
    if min_receivable > 0:
        df = df[df["recv_now"] >= float(min_receivable)]
    if df.empty:
        return None, None, df
    
    symbol = st.session_state.get("currency_symbol", "₹")

    conf = {
        "receipts":   ("rcp_now","delta_rcp_abs",f"Top — Receipts ({symbol})",   f"Bottom — Receipts ({symbol})",   "money"),
        "receivable": ("recv_now","delta_recv_abs",f"Top — Receivable ({symbol})",f"Bottom — Receivable ({symbol})","money"),
        "delta_rcp_abs":("delta_rcp_abs",None,   f"Top — MoM Δ Receipts ({symbol})",f"Bottom — MoM Δ Receipts ({symbol})","money"),
        "efficiency": ("eff_pct","delta_eff_pp","Top — Efficiency (%)","Bottom — Efficiency (%)","percent"),
        "delta_eff_pp":("delta_eff_pp",None,"Top — MoM Δ Efficiency (pp)","Bottom — MoM Δ Efficiency (pp)","pp"),
        "delta_rcp_pct":("delta_rcp_pct",None,"Top — MoM Δ Receipts (%)","Bottom — MoM Δ Receipts (%)","percent"),
        }

    metric_key, delta_col, t_top, t_bot, value_kind = conf.get(metric, conf["efficiency"])
    titles = titles or (t_top, t_bot)

    df_sorted = df.sort_values(metric_key, ascending=False)
    top = df_sorted.head(top_n).copy()
    bot = df_sorted.tail(top_n).copy()

    def _fmt_value(v):
        if value_kind == "money":   return _fmt_inr(v)
        if value_kind == "percent": return f"{float(v):.1f}%"
        if value_kind == "pp":      return f"{float(v):+.1f} pp"
        return f"{float(v):.2f}"

    def _decorate(names):
        out = []
        for nm in names[::-1]:  # reverse for top-to-bottom display
            out.append(f"**{nm}**" if highlight_branch and nm.lower() == highlight_branch.lower() else nm)
        return out

    def _build_items(vals, color):
        items = []
        for v in vals[::-1]:
            items.append({
                "value": round(float(v), 2),
                "label": {"show": True, "position": "right", "formatter": _fmt_value(v)},
                "itemStyle": {"color": color, "borderRadius": [6, 6, 6, 6]},
            })
        return items

    top_names = _decorate(top["branch"].tolist())
    bot_names = _decorate(bot["branch"].tolist())
    top_vals  = top[metric_key].tolist()
    bot_vals  = bot[metric_key].tolist()

    # choose colors (fallback if a palette isn't provided by caller)
    green = (palette or {}).get("success", "#10b981")
    red   = (palette or {}).get("danger",  "#ef4444")
    title_color = (palette or {}).get("title", "#6b7280")
    border_rgba = (palette or {}).get("border_rgba", "rgba(30, 65, 103, 0.12)")

    top_items = _build_items(top_vals, green)
    bot_items = _build_items(bot_vals, red)

    def _option(title, names, items, is_percent):
        return {
            "title": {"text": title, "left": 6, "textStyle": {"color": title_color, "fontSize": 13}},
            "tooltip": {"trigger": "item"},
            "grid": {"left": 8, "right": 24, "top": 28, "bottom": 8, "containLabel": True},
            "xAxis": {
                "type": "value",
                "axisLabel": {"formatter": "{value}%" if is_percent else "{value}", "color": title_color},
                "splitLine": {"lineStyle": {"type": "dashed", "color": border_rgba}},
            },
            "yAxis": {"type": "category", "data": names, "axisLabel": {"color": title_color, "margin": 10}},
            "series": [{
                "type": "bar",
                "barWidth": 18,
                "barCategoryGap": "24%",
                "data": items,
                "z": 3,
            }],
        }

    is_percent_axis = (value_kind == "percent")
    opt_top = _option(titles[0], top_names, top_items, is_percent_axis)
    opt_bot = _option(titles[1], bot_names, bot_items, is_percent_axis)

    export_cols = [
        "branch","eff_now","eff_prev","delta_eff_pp","rcp_now","rcp_prev",
        "delta_rcp_abs","delta_rcp_pct","recv_now","recv_prev","delta_recv_abs","delta_recv_pct"
    ]
    export_df = df[export_cols].copy()
    return opt_top, opt_bot, export_df

