# branch_report_duck.py — Branch rollup using compute_all_38_duckdb (Parquet + DuckDB)

from __future__ import annotations

import io
from pathlib import Path
from datetime import date
from typing import Dict, Any
import os, tempfile, platform

import numpy as np
import pandas as pd
import streamlit as st
from streamlit_echarts import st_echarts

# ===== import your loan calculator (38 columns) =====
from Calculation.loan_duckdb import compute_all_38_duckdb

# =========================================
#                  PATHS
# =========================================
import json, hashlib
from tools.config_paths import PARQUET_ROOT

DISB_SUBDIR  = "disbursement"
RECV_SUBDIR  = "receipt"
CONFIG_PATH  = "config/loan_rules.json"   # optional; will fallback to dataclass defaults

# --- Currency helpers (reuse the same ones you used elsewhere) ---
from simple_pay.service.helper import get_selected_currency_code, get_currency_name_by_code

# If you want symbol from DB like the other page, bring its helper here.
# If not, this fallback returns ₹ for INR and "CODE " for others.
@st.cache_data(ttl=60)
def get_currency_symbol_by_code(code: str) -> str | None:
    # If you have a DB-backed version already, you can import it instead.
    # This lightweight fallback avoids DB and just maps INR to ₹.
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

def _fmt_money(n: float, symbol: str | None = None, decimals: int = 2) -> str:
    symbol = symbol or st.session_state.get("currency_symbol", "₹")
    return f"{symbol}{fmt_inr_indian_grouping(n, decimals)}"

# =========================================
#                CSS
# =========================================
def set_custom_style():
    st.markdown("""
    <style>
    :root {
        --brand:#1f6feb; --brand-2:#0ea5e9; --success:#10b981; --warning:#f59e0b; --danger:#ef4444; --indigo:#7c3aed;
        --surface:#ffffff; --surface-2:#fbfdff; --border:rgba(30,65,103,0.08);
        --shadow:0 6px 14px rgba(18,38,63,0.06); --shadow-hover:0 10px 22px rgba(18,38,63,0.10);
        --title:#6b7280; --value:#0f172a;
    }
    @media (prefers-color-scheme: dark) {
        :root { --surface:#0b1220; --surface-2:#0f1626; --border:rgba(255,255,255,0.08);
                --shadow:0 6px 14px rgba(0,0,0,0.35); --shadow-hover:0 10px 22px rgba(0,0,0,0.45);
                --title:#9aa4b2; --value:#eef2ff; }
    }
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
    .stat-title { font-size:22px; color:var(--title); font-weight:700; margin:2px 0 4px 0; line-height:1.2; letter-spacing:.2px; }
    .stat-value { font-size:22px; font-weight:700; color:var(--value); margin:0; line-height:1.15; }
    .theme-brand  { --accent:var(--brand);  background:linear-gradient(180deg, color-mix(in oklab, var(--brand) 8%, var(--surface)) 0%, var(--surface-2) 85%);  border-color:color-mix(in oklab, var(--brand) 18%, var(--border)); }
    .theme-cyan   { --accent:var(--brand-2);background:linear-gradient(180deg, color-mix(in oklab, var(--brand-2)10%, var(--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var(--brand-2)18%, var(--border));}
    .theme-success{ --accent:var(--success);background:linear-gradient(180deg, color-mix(in oklab, var(--success)10%, var(--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var(--success)18%, var(--border));}
    .theme-warning{ --accent:var(--warning);background:linear-gradient(180deg, color-mix(in oklab, var(--warning)10%, var(--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var(--warning)18%, var(--border));}
    .theme-danger { --accent:var(--danger); background:linear-gradient(180deg, color-mix(in oklab, var(--danger) 10%, var(--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var(--danger) 18%, var(--border));}
    .theme-indigo { --accent:var(--indigo); background:linear-gradient(180deg, color-mix(in oklab, var(--indigo) 10%, var(--surface)) 0%, var(--surface-2) 85%); border-color:color-mix(in oklab, var(--indigo) 18%, var(--border));}
    .section-title { font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:.04em; color:var(--title); margin:16px 2px 8px; }
    .totals-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:10px; }
    .total-card { position:relative; background:linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 100%);
        border-radius:14px; padding:12px 14px; box-shadow:var(--shadow); border:1px solid var(--border);
        min-height:64px; display:grid; grid-template-columns:1fr auto; align-items:center; }
    .total-card::before { content:""; position:absolute; inset:0 0 auto 0; height:3px; background:var(--accent, var(--brand)); opacity:.9; }
    .total-label { font-size:13px; color:var(--title); font-weight:700; }
    .total-value { font-weight:800; font-size:15px; color:var(--value); }
    div[data-testid^="stDateInput"], div[data-testid*="date_input"]{margin-bottom:0!important;padding-bottom:0!important;}
    div[data-testid^="stHorizontalBlock"]{margin-top:-50!important;padding-top:0!important;}
    div[data-testid^="stVerticalBlock"]>div[data-testid^="stHorizontalBlock"]{margin-top:-50!important;padding-top:0!important;}
    [data-testid="stMetric"],[data-testid="stCard"],.stMetric,.stCard{margin-top:-50!important;margin-bottom:0!important;padding-top:0!important;padding-bottom:0!important;}
    </style>
    """, unsafe_allow_html=True)

# =========================================
#           TOP-RIGHT CLOSE (optional global)
# =========================================
def add_top_right_close_button(offset_top: int = 120, target_page: str = "pages/Reports.py"):
    st.markdown(f"""
        <style>
        .top-right-btn {{
            position: fixed; top: {offset_top}px; right: 12px; z-index: 99999;
        }}
        .top-right-btn button {{
            width: 36px; height: 36px; border-radius: 999px;
            background: #111827; color: #fff; border: 1px solid rgba(17,24,39,.15);
            font-weight: 800; font-size: 18px; box-shadow: 0 6px 14px rgba(18,38,63,.18);
            cursor: pointer;
        }}
        .top-right-btn button:hover {{ background: #272f3c; }}
        </style>
        <div class="top-right-btn">
    """, unsafe_allow_html=True)
    if st.button("✕", key="go_reports_btn", help="Go to Reports"):
        st.switch_page(target_page)
    st.markdown("</div>", unsafe_allow_html=True)
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

# =========================================
#         CACHE (file-backed CSV)
# =========================================
# =========================================
#         CACHE (safe, user-writable)
# =========================================

# ---- tiny helpers used by cache ----
import json, hashlib

def _cache_key(prefix: str, payload: Dict[str, Any]) -> str:
    s = json.dumps(payload, sort_keys=True, default=str)
    return f"{prefix}_{hashlib.md5(s.encode('utf-8')).hexdigest()}"

def _load_cache(prefix: str, payload: Dict[str, Any]) -> pd.DataFrame | None:
    fp = CACHE_DIR / f"{_cache_key(prefix, payload)}.csv"
    if fp.exists():
        try:
            return pd.read_csv(fp)
        except Exception:
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
    return None


def _pick_cache_dir() -> Path:
    # 1) Env override (best for services/EXE)
    env_dir = os.getenv("SIMPLEPAY_CACHE_DIR")
    if env_dir:
        p = Path(env_dir)
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass  # fall through

    # 2) Per-user cache
    try:
        if platform.system().lower().startswith("win"):
            base = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
            p = base / "SimplePay" / "cache"
        else:
            base = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
            p = base / "simplepay"
        p.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        pass

    # 3) CWD if writable
    try:
        p = Path(".simple_pay_cache")
        p.mkdir(parents=True, exist_ok=True)
        (p / ".touch").write_text("", encoding="utf-8")
        (p / ".touch").unlink(missing_ok=True)
        return p
    except Exception:
        pass

    # 4) OS temp (last resort)
    p = Path(tempfile.gettempdir()) / "simplepay_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p

CACHE_DIR = _pick_cache_dir()

def _ensure_dir_ok(path: Path) -> Path:
    if path.exists() and not path.is_dir():
        try:
            path.rename(path.with_suffix(path.suffix + ".bak"))
        except Exception:
            pass
        path.mkdir(parents=True, exist_ok=True)
    return path

CACHE_DIR = _ensure_dir_ok(CACHE_DIR)

def _save_cache(df: pd.DataFrame, prefix: str, payload: Dict[str, Any]) -> None:
    """Atomic write to minimize permission/locking issues on Windows."""
    fp = CACHE_DIR / f"{_cache_key(prefix, payload)}.csv"
    tmp = fp.with_suffix(".csv.tmp")
    try:
        df.to_csv(tmp, index=False)
        os.replace(tmp, fp)  # atomic on Windows/POSIX
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass

# =========================================
#     DUCKDB → LOAN-LEVEL → BRANCH ROLLUP
# =========================================
COL_REGION               = "Region"
COL_LOAN_AMOUNT          = "Loan Amount"
COL_PRINCIPAL_REPAID_0_90= "Total Principal Repaid (0–90 days)"
COL_INTEREST_ACCRUED     = "Total Interest Accrued"
COL_INTEREST_PAID        = "Total Interest Paid"
COL_PENALTIES_PAID       = "Total Penalties Paid"
COL_PENALTIES_BAL        = "Total Penalties Balance"
COL_PRINCIPAL_BAL_90     = "Principal Balance (to 90 days)"

NUMERIC_DEFAULTS = [
    COL_LOAN_AMOUNT, COL_PRINCIPAL_REPAID_0_90, COL_INTEREST_ACCRUED,
    COL_INTEREST_PAID, COL_PENALTIES_PAID, COL_PENALTIES_BAL, COL_PRINCIPAL_BAL_90
]

def _coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df2 = df.copy()
    for c in cols:
        if c in df2.columns:
            df2[c] = pd.to_numeric(df2[c], errors="coerce").fillna(0.0)
    return df2

def _downcast_financials(df: pd.DataFrame) -> pd.DataFrame:
    df2 = df.copy()
    for c in df2.columns:
        if c == "Branch": continue
        if pd.api.types.is_numeric_dtype(df2[c]):
            df2[c] = pd.to_numeric(df2[c], errors="coerce").fillna(0.0).astype("float32")
    return df2

def _limit_top_n_with_others(df: pd.DataFrame, n: int = 25) -> pd.DataFrame:
    if df.empty: return df
    df = df.copy()
    df["_Total_Received_TMP"] = (
        df.get("Principal_Repaid", 0).fillna(0) +
        df.get("Interest_Received", 0).fillna(0) +
        df.get("Penalty_Received", 0).fillna(0)
    )
    top = df.nlargest(n, "_Total_Received_TMP")
    if len(df) > n:
        rest = df.drop(top.index)
        others_vals = {col: [rest[col].sum()] if col != "Branch" else ["Others"] for col in df.columns if col != "_Total_Received_TMP"}
        others = pd.DataFrame(others_vals)
        top = pd.concat([top.drop(columns=["_Total_Received_TMP"], errors="ignore"),
                         others[df.columns.drop("_Total_Received_TMP")]], ignore_index=True)
    else:
        top = top.drop(columns=["_Total_Received_TMP"], errors="ignore")
    return top

@st.cache_data(ttl=300)
def get_branch_rollup_from_duckdb(
    start_date: str,
    end_date: str,
    parquet_root: str | Path,
    *,
    disb_subdir: str = "disbursement",
    recv_subdir: str = "receipt",
    config_path: str = "config/loan_rules.json",
    speed_mode: bool = False,
) -> pd.DataFrame:
    loan = compute_all_38_duckdb(
        start_date=start_date,
        end_date=end_date,
        parquet_root=parquet_root,
        disb_subdir=disb_subdir,
        recv_subdir=recv_subdir,
        config_path=config_path,
    )

    # --- Map compute_all_38_duckdb output to the canonical column names this page expects ---

    # Principal paid across all windows (0–90)
    principal_paid_cols = [
        "Principal_paid_30",
        "Principal_paid_31_45",
        "Principal_paid_46_60",
        "Principal_paid_61_90",
    ]
    for c in principal_paid_cols:
        if c not in loan.columns:
            loan[c] = 0.0

    # Penalty paid/balance across windows
    pen_paid_cols = ["Penalty_paid_31_45", "Penalty_paid_46_60", "Penalty_paid_61_90"]
    pen_bal_cols  = ["Penalty_balance_31_45", "Penalty_balance_46_60", "Penalty_balance_61_90"]
    for c in pen_paid_cols + pen_bal_cols:
        if c not in loan.columns:
            loan[c] = 0.0

    # 1) Region
    if COL_REGION not in loan.columns:
        loan[COL_REGION] = loan.get("branch", loan.get("Branch", "Unknown")).astype(str)

    # 2) Loan Amount
    loan[COL_LOAN_AMOUNT] = pd.to_numeric(loan.get("disb_amount", 0.0), errors="coerce").fillna(0.0)

    # 3) Total Principal Repaid (0–90 days)
    loan[COL_PRINCIPAL_REPAID_0_90] = (
        pd.to_numeric(loan["Principal_paid_30"], errors="coerce").fillna(0.0) +
        pd.to_numeric(loan["Principal_paid_31_45"], errors="coerce").fillna(0.0) +
        pd.to_numeric(loan["Principal_paid_46_60"], errors="coerce").fillna(0.0) +
        pd.to_numeric(loan["Principal_paid_61_90"], errors="coerce").fillna(0.0)
    )

    # 4) Interest (accrued/paid) — from 0–30 window per your SQL
    loan[COL_INTEREST_ACCRUED] = pd.to_numeric(loan.get("Interest_accrued_30", 0.0), errors="coerce").fillna(0.0)
    loan[COL_INTEREST_PAID]    = pd.to_numeric(loan.get("Interest_paid_30",    0.0), errors="coerce").fillna(0.0)

    # 5) Penalties (paid & balance) aggregated across 31–90
    loan[COL_PENALTIES_PAID] = sum(
        pd.to_numeric(loan[c], errors="coerce").fillna(0.0) for c in pen_paid_cols
    )
    loan[COL_PENALTIES_BAL] = sum(
        pd.to_numeric(loan[c], errors="coerce").fillna(0.0) for c in pen_bal_cols
    )

    # 6) Principal Balance (to 90 days) — last window’s principal balance
    loan[COL_PRINCIPAL_BAL_90] = pd.to_numeric(
        loan.get("Principal_balance_61_90", 0.0), errors="coerce"
    ).fillna(0.0)


    loan = _coerce_numeric(loan, NUMERIC_DEFAULTS)

    grouped = loan.groupby(COL_REGION, dropna=False).agg({
        COL_LOAN_AMOUNT: "sum",
        COL_PRINCIPAL_REPAID_0_90: "sum",
        COL_INTEREST_ACCRUED: "sum",
        COL_INTEREST_PAID: "sum",
        COL_PENALTIES_PAID: "sum",
        COL_PENALTIES_BAL: "sum",
        COL_PRINCIPAL_BAL_90: "sum",
    }).reset_index()

    out = pd.DataFrame({
        "Branch": grouped[COL_REGION].astype(str),
        "Total_Disbursed": grouped[COL_LOAN_AMOUNT],
        "Total_Collected": grouped[COL_PRINCIPAL_REPAID_0_90] + grouped[COL_INTEREST_PAID] + grouped[COL_PENALTIES_PAID],
        "Penalty_Charged": grouped[COL_PENALTIES_PAID] + grouped[COL_PENALTIES_BAL],
        "Penalty_Received": grouped[COL_PENALTIES_PAID],
        "Penalty_Balance": grouped[COL_PENALTIES_BAL],
        "Interest_Chargeable": grouped[COL_INTEREST_ACCRUED],
        "Interest_Received": grouped[COL_INTEREST_PAID],
        "Interest_Balance": grouped[COL_INTEREST_ACCRUED] - grouped[COL_INTEREST_PAID],
        "Principal_Repaid": grouped[COL_PRINCIPAL_REPAID_0_90],
        "Principal_Balance": grouped[COL_PRINCIPAL_BAL_90],
    })

    if speed_mode:
        out = _limit_top_n_with_others(out, n=25)

    return _downcast_financials(out)

# =========================================
#              PARETO CHART
# =========================================
def chart_pareto_disbursed_vs_received(df: pd.DataFrame, key_prefix: str = "pareto") -> None:
    symbol = st.session_state.get("currency_symbol", "₹")
    req = {"Branch", "Total_Disbursed", "Total_Collected"}
    missing = [c for c in req if c not in df.columns]
    if missing:
        st.warning(f"Missing columns for Pareto: {', '.join(missing)}"); return

    x = df[["Branch", "Total_Disbursed", "Total_Collected"]].copy()
    x[["Total_Disbursed", "Total_Collected"]] = x[["Total_Disbursed", "Total_Collected"]].apply(pd.to_numeric, errors="coerce").fillna(0.0)

    x = x.sort_values("Total_Collected", ascending=False).reset_index(drop=True)
    cats = x["Branch"].astype(str).tolist()
    rec  = x["Total_Collected"].to_numpy(dtype=float)
    dis  = x["Total_Disbursed"].to_numpy(dtype=float)

    total_rec = rec.sum() if rec.sum() != 0 else 1.0
    total_dis = dis.sum() if dis.sum() != 0 else 1.0
    rec_cum_pct = (np.cumsum(rec) / total_rec * 100).round(2).tolist()
    dis_cum_pct = (np.cumsum(dis) / total_dis * 100).round(2).tolist()

    visible_span = min(10, max(1, len(cats)))
    start_val, end_val = 0, max(0, visible_span - 1)

    option = {
        "tooltip": {
            "trigger": "axis",
            "axisPointer": {"type": "cross"},
            "formatter": f"""
                function (params) {{
                const money = (v) => {{
                    try {{
                    const n = Number(v||0);
                    return n.toLocaleString('en-IN', {{minimumFractionDigits:2, maximumFractionDigits:2}});
                    }} catch(e) {{ return v; }}
                }};
                let out = '';
                params.forEach(p => {{
                    if (p.seriesType === 'bar') {{
                    out += `<div><b>${{p.seriesName}}</b>: {st.session_state.get("currency_symbol","₹")}${{money(p.value)}}</div>`;
                    }} else {{
                    out += `<div>${{p.seriesName}}: ${{p.value}}%</div>`;
                    }}
                }});
                return out;
                }}
            """
        },
        "legend": {"top": 0},
        "grid": {"left": 70, "right": 70, "top": 40, "bottom": 100},
        "xAxis": {"type": "category", "data": cats, "axisLabel": {"rotate": 45, "hideOverlap": True}},
        "yAxis": [
            {"type": "value", "name": f"{symbol} Amount"},
            {"type": "value", "min": 0, "max": 100, "name": "Cumulative %"}
        ],
        "dataZoom": [
            {"type": "slider", "xAxisIndex": 0, "startValue": start_val, "endValue": end_val,
            "minValueSpan": visible_span, "maxValueSpan": visible_span, "zoomLock": True},
            {"type": "inside", "xAxisIndex": 0, "moveOnMouseWheel": True, "zoomOnMouseWheel": False,
            "minValueSpan": visible_span, "maxValueSpan": visible_span, "zoomLock": True}
        ],
        "series": [
            {"name": "Received",  "type": "bar",  "data": x["Total_Collected"].round(2).tolist(), "barMaxWidth": 28, "z": 3},
            {"name": "Disbursed", "type": "bar",  "data": x["Total_Disbursed"].round(2).tolist(), "barGap": "-35%",
            "barMaxWidth": 28, "itemStyle": {"opacity": 0.35}, "z": 2},
            {"name": "Cum. Received %",  "type": "line", "yAxisIndex": 1, "smooth": True,
            "data": rec_cum_pct, "symbol": "circle",
            "markLine": {"symbol": "none", "data": [{"yAxis": 80, "name": "80% rule"}], "label": {"formatter": "{b}"}}},
            {"name": "Cum. Disbursed %", "type": "line", "yAxisIndex": 1, "smooth": True,
            "data": dis_cum_pct, "symbol": "emptyCircle", "lineStyle": {"type": "dashed"}}
        ],
        "animationDuration": 400
    }

    
    st_echarts(options=option, height=560, key=f"{key_prefix}_chart")

# =========================================
#                  PAGE (rearranged)
# =========================================
def branch_report():
    set_custom_style()
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

    # Defaults in session
    if "branch_start_date" not in st.session_state:
        st.session_state["branch_start_date"] = date(2024, 2, 1)
    if "branch_end_date" not in st.session_state:
        st.session_state["branch_end_date"] = date(2024, 2, 29)

    # ------- Compact form row: start | end | Show | Close -------
    with st.form("branch_date_form", clear_on_submit=False):
        # label, input, label, input, show, close
        c1, c2, c3, c4, c5, c6 = st.columns([0.6, 1.0, 0.6, 1.0, 0.8, 0.8])

        # --- Start Date label ---
        with c1:
            st.markdown(
                "<label style='font-size:18px; font-weight:800; margin:0; display:flex; align-items:center;'>Start Date</label>",
                unsafe_allow_html=True
            )

        # --- Start Date input ---
        with c2:
            start = st.date_input(
                "",
                value=st.session_state["branch_start_date"],
                key="branch_start_date_input",
                label_visibility="collapsed"
            )

        # --- End Date label ---
        with c3:
            st.markdown(
                "<label style='font-size:18px; font-weight:800; margin:0; display:flex; align-items:center;'>End Date</label>",
                unsafe_allow_html=True
            )

        # --- End Date input ---
        with c4:
            end = st.date_input(
                "",
                value=st.session_state["branch_end_date"],
                key="branch_end_date_input",
                label_visibility="collapsed"
            )

        # --- Show button ---
        with c5:
            submitted = st.form_submit_button("Show report", use_container_width=True)

        # --- Close button ---
        with c6:
            close_clicked = st.form_submit_button("Close", use_container_width=True)

    # Handle Close
    if close_clicked:
        try:
            st.switch_page("pages/Reports.py")
        except Exception:
            pass

    # Guard until Show is clicked
    if not submitted:
        st.info("Pick a start and end date, then click **Show report** to load the branch report.")
        return  # or st.stop() if this is top-level

    # Validate range
    if start > end:
        st.warning("Start Date cannot be after End Date.")
        return  # or st.stop()

    # Persist selection
    st.session_state["branch_start_date"] = start
    st.session_state["branch_end_date"]   = end

    start_str = pd.to_datetime(start).strftime("%Y-%m-%d")
    end_str   = pd.to_datetime(end).strftime("%Y-%m-%d")

    st.markdown('<div style="border-top: 3px solid #000000; margin: 20px 0; width: 100%;"></div>', unsafe_allow_html=True)

    try:
        with st.spinner(f"Loading branch report (DuckDB) from {start_str} to {end_str} ..."):
            df = get_branch_rollup_from_duckdb(
                start_date=start_str,
                end_date=end_str,
                parquet_root=PARQUET_ROOT,
                disb_subdir=DISB_SUBDIR,
                recv_subdir=RECV_SUBDIR,
                config_path=CONFIG_PATH,
                speed_mode=False,
            )
    except Exception as e:
        st.error(f"Error while computing DuckDB report: {e}")
        return  # or st.stop()

    if df.empty:
        st.info(f"No records between {start} and {end}.")
        return

    

    # --- Pareto Chart ---
    st.markdown('<div class="section-title">Disbursed vs Received</div>', unsafe_allow_html=True)
    chart_pareto_disbursed_vs_received(df, key_prefix=f"pareto_{start_str}_{end_str}")

    st.markdown('<div style="border-top: 3px solid #000000; margin: 20px 0; width: 100%;"></div>', unsafe_allow_html=True)


    # --- Branch Table ---
    st.markdown(
        f'<div class="section-title"> Showing branch records from <b>{start_str}</b> to <b>{end_str}</b>. Branches: <b>{len(df)}</b></div>',
        unsafe_allow_html=True
    )

    col_order = [
        "Branch", "Total_Disbursed", "Total_Collected", "Penalty_Charged", "Penalty_Received",
        "Penalty_Balance", "Interest_Chargeable", "Interest_Received", "Interest_Balance",
        "Principal_Repaid", "Principal_Balance"
    ]
    show_cols = [c for c in col_order if c in df.columns]

    # Keep a numeric copy for Excel
    # Keep a numeric copy for Excel
    df_display = df.copy()
    for c in show_cols:
        if c != "Branch":
            df_display[c] = pd.to_numeric(df_display[c], errors="coerce").round(2)

    # For on-screen table: Indian grouping, NO currency symbol
    df_view = df_display.copy()
    for c in show_cols:
        if c != "Branch":
            df_view[c] = df_view[c].apply(lambda v: fmt_inr_indian_grouping(v, 2))

    df_view.index = range(1, len(df_view) + 1)
    st.dataframe(df_view[show_cols], use_container_width=True, height=320)

    # --- Combined Download Row ---
    col1, col2 = st.columns([1, 1])  # equal spacing

    with col1:
        capture_script = """
        <style>
        .custom-download-btn {
            background: #22c55e; color: white; padding: 12px 20px;
            border: none; border-radius: 25px; font-size: 14px;
            font-weight: 600; cursor: pointer;
            box-shadow: 0 4px 8px rgba(0,0,0,0.25);
            transition: all 0.2s ease;
        }
        .custom-download-btn:hover {
            background: #16a34a; transform: translateY(-2px);
        }
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
        <button class="custom-download-btn" onclick="downloadImage()">📸 Download Dashboard</button>
        """
        st.components.v1.html(capture_script, height=70)

    with col2:
        def to_excel(df_):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_.to_excel(writer, index=False, sheet_name="Sheet1")
            return output.getvalue()

        excel_file = to_excel(df_display)

        st.download_button(
            label="📥 Download Table",
            data=excel_file,
            file_name="branch.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
