from __future__ import annotations

import streamlit as st
import time
import os
import pandas as pd
from datetime import datetime
import tempfile
import io  
import mysql.connector
from tools.refresh_parquet_cache import refresh_once

from sqlalchemy import create_engine, text
from simple_pay.utils.database_connection import DatabaseConnection, DatabaseConnectionPool

# ---- BOOTSTRAP: make sure `currency` and `app_settings` exist (run once) ----
try:
    _boot_conn = DatabaseConnectionPool.get_connection()
    DatabaseConnection.ensure_currency_and_app_settings(_boot_conn)
finally:
    try:
        _boot_conn.close()
    except Exception:
        pass
# ---------------------------------------------------------------------------


from simple_pay.service.disbursement_service import DisbursementService
from simple_pay.service.reciept_service import Reciept_service

from simple_pay.utils.validation import validate_file

from simple_pay.service.helper  import *

import chardet

# ---------- SAFE APP DATA PATHS ----------
from pathlib import Path
import sys, tempfile, os

APP_NAME = "SimplePay"

def _safe_mkdir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_error_dir() -> str:
    """
    Always return a writable folder for error reports.
    Order:
      1) SIMPLEPAY_DATA_DIR\error_reports (if env var set)
      2) %LOCALAPPDATA%\SimplePay\error_reports
      3) next to package / frozen bundle (error_reports)
      4) OS temp\SimplePay\error_reports
    """
    # 1) explicit override
    override = os.getenv("SIMPLEPAY_DATA_DIR")
    if override:
        try:
            return str(_safe_mkdir(Path(override) / "error_reports"))
        except Exception:
            pass

    # 2) per-user AppData on Windows (safe for services/EXE)
    local_appdata = os.getenv("LOCALAPPDATA")
    if local_appdata:
        try:
            return str(_safe_mkdir(Path(local_appdata) / APP_NAME / "error_reports"))
        except Exception:
            pass

    # 3) next to the package / PyInstaller bundle
    try:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
        return str(_safe_mkdir(base / "error_reports"))
    except Exception:
        pass

    # 4) last resort: temp
    return str(_safe_mkdir(Path(tempfile.gettempdir()) / APP_NAME / "error_reports"))


params = st.query_params
user_id = params.get("user_id", None)
user_id = st.session_state.get("user_id")
# print("user_id session state",user_id)
u_id = "u_id:" + str(st.session_state.get("u_id"))
ERROR_DIR = get_error_dir()

from simple_pay.service.helper import validation

# -----------------------
# DB CONFIG
# -----------------------
DB_USER = "root"
DB_PWD  = ""
DB_HOST = "localhost"
DB_PORT = 3306
DB_NAME = "keny"

CONN_STR = f"mysql+pymysql://{DB_USER}:{DB_PWD}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
engine = create_engine(
    CONN_STR,
    pool_pre_ping=True,
    pool_size=10,      
    max_overflow=20
)

from pathlib import Path
from urllib.parse import urlparse

import json, hashlib
from datetime import datetime

def _upsert_file_status(file_type: str,
                        last_filename: str | None,
                        min_date, max_date,
                        record_count: int,
                        total_amount):
    """
    Upsert into your existing `file_status` table (ENUM PK on file_type).
    This drives the 'Last Updated' sidebar.
    """
    conn = None; cur = None
    try:
        conn = DatabaseConnectionPool.get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO file_status
                (file_type, last_upload, min_date, max_date, record_count, total_amount, last_filename, last_hash)
            VALUES
                (%s, NOW(), %s, %s, %s, %s, %s, NULL)
            ON DUPLICATE KEY UPDATE
                last_upload = VALUES(last_upload),
                min_date    = VALUES(min_date),
                max_date    = VALUES(max_date),
                record_count= VALUES(record_count),
                total_amount= VALUES(total_amount),
                last_filename = VALUES(last_filename)
        """, (
            file_type,
            (min_date.strftime("%Y-%m-%d") if hasattr(min_date, "strftime") else min_date),
            (max_date.strftime("%Y-%m-%d") if hasattr(max_date, "strftime") else max_date),
            int(record_count) if record_count is not None else None,
            float(total_amount) if total_amount is not None else None,
            last_filename
        ))
        conn.commit()
    finally:
        try: cur and cur.close()
        except: pass
        try: conn and conn.close()
        except: pass


def _insert_upload_summary(file_type: str,
                           file_name: str,
                           valid_df: pd.DataFrame | None,
                           error_df: pd.DataFrame | None,
                           total_amount,
                           min_date, max_date):
    """
    Append a row to your existing `upload_summary` table.
    This drives the bottom 'Summary table'.
    """
    rows_ok  = len(valid_df) if valid_df is not None else 0
    rows_err = len(error_df) if error_df is not None else 0
    record_count = rows_ok + rows_err

    conn = None; cur = None
    try:
        conn = DatabaseConnectionPool.get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO upload_summary
              (file_name, record_count, valid_rows, error_rows, total_amount,
               min_date, max_date, created_at, file_type)
            VALUES
              (%s, %s, %s, %s, %s, %s, %s, NOW(), %s)
        """, (
            file_name,
            record_count, rows_ok, rows_err,
            (float(total_amount) if total_amount is not None else None),
            (min_date.strftime("%Y-%m-%d") if hasattr(min_date, "strftime") else min_date),
            (max_date.strftime("%Y-%m-%d") if hasattr(max_date, "strftime") else max_date),
            file_type
        ))
        conn.commit()
    finally:
        try: cur and cur.close()
        except: pass
        try: conn and conn.close()
        except: pass


APP_ROOT = Path(__file__).resolve().parents[1]

def get_company_info():
    with engine.connect() as conn:
        res = conn.execute(text("""
            SELECT company_name, logo_url
            FROM company_info
            ORDER BY created_at DESC
            LIMIT 1
        """))
        return res.mappings().first()

def resolve_logo_path(logo_url: str) -> str | None:
    """Return a valid URL/path to an existing image, else None."""
    if not logo_url:
        return None

    # 1) External URL
    u = urlparse(logo_url)
    if u.scheme in ("http", "https"):
        return logo_url

    # 2) Local path
    p = Path(logo_url)
    if not p.is_absolute():
        p = (APP_ROOT / p).resolve()  # treat as relative to project root

    return str(p) if p.exists() else None

with st.sidebar:
    company = get_company_info()
    if company:
        safe_logo = resolve_logo_path(company.get("logo_url", ""))
        if safe_logo:
            st.image(safe_logo, use_container_width=True) # new Streamlit API (replaces use_container_width)
        else:
            # optional, for debugging during setup—remove later:
            st.caption("⚠️ Logo not found. Check company_info.logo_url or file location.")
        st.markdown(f"### {company['company_name']}")
    st.divider()

st.markdown("""
<style>
        /* Hide sidebar navigation items containing 'Main' or 'Login' */
        section[data-testid="stSidebar"] ul li a:has(p:contains("Main")) {
            display: none !important;
        }
        section[data-testid="stSidebar"] ul li a:has(p:contains("Login")) {
            display: none !important;
        }
</style>
""", unsafe_allow_html=True)
with st.sidebar:
    if st.button("📊 Data_Upload",key="reports_nav_data_upload"):
        user_id = st.session_state.get("user_id")
        st.session_state["user_id"] = user_id
        st.switch_page("pages/Data_Upload.py")
    if st.button("📈 Reports",key="reports_nav_reports") :
        st.switch_page("pages/Reports.py")
    if st.button("🚪 Logout",key="reports_nav_logout"):
        st.session_state.clear()
        st.switch_page("pages/Login.py")
    editor_mode = ""
    with open(r"C:\project_v2\simple-pay-v2\simple_pay\editor\v1.txt", "r") as f:
        editor_mode = f.read().strip().lower()
    if user_id is not None :
        if editor_mode == str(user_id)+u_id or u_id in editor_mode:
            if st.button("Exit Upload mode"):
                with open(r"C:\project_v2\simple-pay-v2\simple_pay\editor\v1.txt", "w") as f:
                    f.write("")
                st.success("System is now in normal mode. Data uploads are enabled.")
                time.sleep(1)
                st.rerun()
        else:
            if editor_mode != "":
                print(editor_mode,"-------------------")
                st.error("System is currently in upload mode. Data uploads are disabled.")
            else:
                if st.button("Upload mode"):
                    with open(r"C:\project_v2\simple-pay-v2\simple_pay\editor\v1.txt", "w") as f:
                        f.write((str(user_id)+u_id))
                    st.success("System is now in upload mode. Data uploads are disabled.")
                    time.sleep(1)
                    st.rerun()
        
        
        

# ------------------- AUTHENTICATION -------------------
if 'authenticated' not in st.session_state or not st.session_state.authenticated:
    st.switch_page("pages/Login.py")

if st.session_state.get('role') != 'admin':
    st.error("You must be an admin to access this page")
    st.stop()


#  only admins will reach here, so put truncate button here
with st.sidebar:
    
    st.divider()
    if st.button("🗑️ Delete Data"):
        st.session_state["confirm_truncate"] = True

    # Confirmation prompt
    if "confirm_truncate" in st.session_state:
        st.warning("⚠ Are you sure you want to delete ALL data? This cannot be undone.")
        c1, c2 = st.columns(2)
        if c1.button(" Yes, Delete"):
            success, msg = truncate_tables()
            if success:
                st.success(msg)
            else:
                st.error(msg)
            del st.session_state["confirm_truncate"]
            time.sleep(1)
            st.rerun()
        if c2.button(" Cancel"):
            del st.session_state["confirm_truncate"]

# ------------------- LOGOUT BUTTON (Top-right) -------------------
st.markdown("""
<style>
/* Remove padding and set height */
.block-container {
    padding: 0rem 2rem 2rem 2rem;
    max-width: 100%;
}

/* Prevent full-page scroll */
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"] {
    height: 100vh !important;
    overflow: hidden !important;
}

/* Make main content scrollable inside */
section.main > div {
    height: calc(100vh - 100px);
    overflow-y: auto;
    padding: 1.5rem;
    background-color: #ffffff;
    border-radius: 10px;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.05);
}

/* Title styling */
h1 {
    font-size: 38px;
    color: #1e3d59;
    font-weight: bold;
    border-left: 6px solid #007acc;
    padding-left: 15px;
}

/* Tab styles */
.stTabs [role="tablist"] {
    border-bottom: 2px solid #ccc;
    margin-bottom: 1rem;
    margin-top: 35px;
}


/* Hide footer */
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)



# ------------------- SIDEBAR: Last Upload Info -------------------
def create_user(username: str, password: str, role: str):
    try:
        db = DatabaseConnection()
        db.connect()
        cur = db.cursor

        # Check if username exists
        cur.execute("SELECT 1 FROM users WHERE username = %s LIMIT 1", (username,))
        if cur.fetchone():
            db.close()
            return False, f"Username '{username}' already exists."

        # Insert user
        cur.execute(
            "INSERT INTO users (username, password, role, created_at) VALUES (%s, %s, %s, %s)",
            (username, password, role, datetime.now())
        )
        db.conn.commit()   # <-- FIXED
        db.close()
        return True, f"User '{username}' created successfully."
    except Exception as e:
        try:
            db.conn.rollback()
            db.close()
        except Exception:
            pass
        return False, f"DB error while creating user: {e}"

def delete_user(username: str):
    try:
        if username == "admin":
            return False, "Cannot delete the 'admin' user."

        db = DatabaseConnection()
        db.connect()
        cur = db.cursor

        cur.execute("SELECT 1 FROM users WHERE username = %s LIMIT 1", (username,))
        if not cur.fetchone():
            db.close()
            return False, f"User '{username}' not found."

        cur.execute("DELETE FROM users WHERE username = %s", (username,))
        db.conn.commit()   # <-- FIXED
        db.close()
        return True, f"User '{username}' deleted successfully."
    except Exception as e:
        try:
            db.conn.rollback()
            db.close()
        except Exception:
            pass
        return False, f"DB error while deleting user: {e}"

def load_users():
    try:
        db = DatabaseConnection()
        db.connect()
        cur = db.cursor
        cur.execute("SELECT username, role, created_at FROM users ORDER BY created_at DESC")
        rows = cur.fetchall()
        db.close()
        return rows
    except Exception as e:
        st.error(f"Database error: {e}")
        return []


def get_latest_dates():
    databaseConnection = None
    try:
        databaseConnection = DatabaseConnection()
        databaseConnection.connect()
        cursor = databaseConnection.cursor
        cursor.execute('SELECT MAX(disb_date) FROM disbursement')
        disb_date = cursor.fetchone()[0]
        cursor.execute('SELECT MAX(receipt_date) FROM receipt')
        inv_date = cursor.fetchone()[0]
        return disb_date, inv_date
    except Exception as e:
        st.error(f"Database error: {str(e)}")
        return None, None
    finally:
        if databaseConnection:
            databaseConnection.close()

def get_last_upload_times():
    """
    Reads from `file_status` (PRIMARY KEY file_type) to show 'Last Updated' per type.
    """
    databaseConnection = None
    try:
        databaseConnection = DatabaseConnection()
        databaseConnection.connect()
        cursor = databaseConnection.cursor
        times = {}
        for file_type in ["Disbursement", "Receipt", "Members", "Branch"]:
            cursor.execute("""
                SELECT last_upload FROM file_status WHERE file_type = %s
            """, (file_type,))
            row = cursor.fetchone()
            times[file_type] = row[0] if row else None
        return times
    except Exception as e:
        import traceback; traceback.print_exc()
        st.error(f"Database error: {str(e)}")
        return {ft: None for ft in ["Disbursement", "Receipt", "Members", "Branch"]}
    finally:
        try:
            if databaseConnection:
                try: cursor and cursor.close()
                except: pass
                databaseConnection.close()
        except Exception:
            pass


with st.sidebar:
    try:
        st.header("Last Updated")
        upload_times = get_last_upload_times()

        def format_time_display(t):
            if not t:
                return "Never"
            if isinstance(t, str):
                try:
                    t = datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
                except:
                    return t
            return t.strftime("%b %d, %Y at %I:%M %p")

        for file_type in ["Disbursement", "Receipt", "Members", "Branch"]:
            st.subheader(file_type)
            st.info(format_time_display(upload_times[file_type]))

        st.divider()
        if st.button("🔄 Refresh Timestamps",key="btn_refresh_timestamps_sidebar"):
            st.rerun()
    except Exception as e:
        import traceback
        traceback.print_exc()
        st.error(f"Error fetching last upload times: {str(e)}")

    
    # --- Currency selection (SIDEBAR) ---
    # st.subheader("Currency Selection")

    # def get_conn():
    #     return mysql.connector.connect(
    #         host="localhost", user="root", password="", database="keny", autocommit=True
    #     )

    # def fetch_currencies():
    #     with get_conn() as conn, conn.cursor() as cur:
    #         cur.execute("SELECT code, name FROM currency ORDER BY name;")
    #         return cur.fetchall()

    # def fetch_current_selection():
    #     with get_conn() as conn, conn.cursor() as cur:
    #         cur.execute("SELECT selected_currency_code FROM app_settings WHERE id=1;")
    #         row = cur.fetchone()
    #         return row[0] if row else None

    # def save_selection(code: str):
    #     with get_conn() as conn, conn.cursor() as cur:
    #         cur.execute("""
    #             INSERT INTO app_settings (id, selected_currency_code)
    #             VALUES (1, %s)
    #             ON DUPLICATE KEY UPDATE selected_currency_code=VALUES(selected_currency_code);
    #         """, (code,))
    #         conn.commit()

    # currs = fetch_currencies()
    # if not currs:
    #     st.info("No currencies found. Please insert some rows into the `currency` table.")
    # else:
    #     code_by_name = {name: code for code, name in currs}
    #     names = list(code_by_name.keys())

    #     current_code = fetch_current_selection()
    #     preselect_name = next((n for n, c in code_by_name.items() if c == current_code), None)
    #     index = names.index(preselect_name) if preselect_name in names else 0

    #     selected_name = st.selectbox("Choose currency", names, index=index, key="currency_select")
    #     if st.button("Save", key="currency_save_sidebar"):
    #         save_selection(code_by_name[selected_name])
    #         # Optional cache bust if you added the helper module:
    #         try:
                
    #             clear_currency_cache()
    #         except Exception:
    #             pass
    #         st.success(f"Saved: {selected_name}")
    #         st.rerun()

    #     st.caption(f"Current setting: {selected_name}")


    # --- Currency (locked from DB; no dropdown) ---
    # service/helper/currency_pref.py
    import mysql.connector
    # Ensure tables exist even if this file is run directly or reloaded
    try:
        _sb_conn = DatabaseConnectionPool.get_connection()
        DatabaseConnection.ensure_currency_and_app_settings(_sb_conn)
    finally:
        try:
            _sb_conn.close()
        except Exception:
            pass


    # -------- DB connection --------
    def get_conn():
        return mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="keny",
            autocommit=True,
        )

    # -------- bootstrapping: make sure something is selected --------
    def _ensure_selection_exists(default_code: str = "USD") -> None:
        """
        If app_settings has no selection, set it to `default_code` if present in `currency`,
        otherwise use the first currency ordered by name.
        """
        with get_conn() as conn, conn.cursor() as cur:
            # already set?
            cur.execute("SELECT selected_currency_code FROM app_settings WHERE id=1")
            row = cur.fetchone()
            if row and row[0]:
                return  # nothing to do

            # pick default_code if it exists, else first currency by name
            cur.execute("SELECT code FROM currency WHERE code=%s LIMIT 1", (default_code,))
            pick = cur.fetchone()
            if not pick:
                cur.execute("SELECT code FROM currency ORDER BY name LIMIT 1")
                pick = cur.fetchone()

            if pick:
                cur.execute(
                    """
                    INSERT INTO app_settings (id, selected_currency_code)
                    VALUES (1, %s)
                    ON DUPLICATE KEY UPDATE selected_currency_code=VALUES(selected_currency_code)
                    """,
                    (pick[0],),
                )
                conn.commit()

    # -------- read current (code, name) --------
    def _fetch_locked_currency() -> tuple[str | None, str | None]:
        """
        Return (code, name) for the currently selected currency, or (None, None) if not found.
        If no selection exists, it will attempt to create one via _ensure_selection_exists().
        """
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.code, c.name
                FROM app_settings a
                JOIN currency c ON c.code = a.selected_currency_code
                WHERE a.id = 1
                """
            )
            row = cur.fetchone()
            if row:
                return row[0], row[1]

        # If we got here, try to bootstrap once and retry
        _ensure_selection_exists(default_code="USD")
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.code, c.name
                FROM app_settings a
                JOIN currency c ON c.code = a.selected_currency_code
                WHERE a.id = 1
                """
            )
            row = cur.fetchone()
            return (row[0], row[1]) if row else (None, None)

    # Convenience accessors used by Reports.py, etc.
    def get_selected_currency_code() -> str | None:
        code, _ = _fetch_locked_currency()
        return code

    def get_selected_currency_name() -> str | None:
        _, name = _fetch_locked_currency()
        return name

    # -------- safe setters (validate against currency table) --------
    def set_currency_by_code(code: str) -> None:
        """Force the selection to a specific ISO code (must exist in `currency`)."""
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM currency WHERE code=%s LIMIT 1", (code,))
            if not cur.fetchone():
                raise ValueError(f"Currency code not found: {code}")
            cur.execute(
                """
                INSERT INTO app_settings (id, selected_currency_code)
                VALUES (1, %s)
                ON DUPLICATE KEY UPDATE selected_currency_code=VALUES(selected_currency_code)
                """,
                (code,),
            )
            conn.commit()

    def set_currency_by_name(name: str) -> None:
        """Force the selection using the human name (e.g. 'Indian Rupee' -> 'INR')."""
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT code FROM currency WHERE name=%s LIMIT 1", (name,))
            row = cur.fetchone()
            if not row:
                raise ValueError(f"Currency name not found: {name}")
            set_currency_by_code(row[0])

    # -------- Option B: direct SQL "one-liner" helpers --------
    def force_currency_code_sql(code: str) -> None:
        """
        Direct SQL update (no validation). Use when you’re sure code exists in `currency`.
        """
        with get_conn() as conn, conn.cursor() as cur:
            # ensure row exists, then update
            cur.execute(
                "INSERT IGNORE INTO app_settings (id, selected_currency_code) VALUES (1, %s)",
                (code,),
            )
            cur.execute(
                "UPDATE app_settings SET selected_currency_code=%s WHERE id=1",
                (code,),
            )
            conn.commit()

    def force_currency_name_sql(name: str) -> None:
        """
        Direct SQL by currency name (e.g. 'Indian Rupee').
        """
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                UPDATE app_settings a
                JOIN currency c ON c.name=%s
                SET a.selected_currency_code = c.code
                WHERE a.id = 1
            """, (name,))
            conn.commit()

    # -------- initialize once on import (optional) --------
    _ensure_selection_exists(default_code="USD")


#-------------------------------VVP QUERY-------------------------------------------------

# UPDATE app_settings SET selected_currency_code='KES' WHERE id=1;

#-------------------------------VVP QUERY-------------------------------------------------

# ------------------- MAIN TABS -------------------
tab1, tab2 = st.tabs(["📁 Data Upload", "👥 User Management"])

# ------------------- TAB 1: DATA UPLOAD -------------------
overlay_css = """
<style>
[data-testid="stAppViewContainer"]::before {
    content: "";
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background-color: rgba(255,255,255,0.6);
    z-index: 9999;
    display: none;
}
.overlay-active[data-testid="stAppViewContainer"]::before {
    display: block;
}
</style>
"""

# databaseConnection = DatabaseConnection()
# databaseConnection.connect()
# cursor = databaseConnection.cursor
# cursor.execute("SELECT * FROM editor)

    
editor_mode = ""
with open(r"C:\project_v2\simple-pay-v2\simple_pay\editor\v1.txt", "r") as f:
    editor_mode = f.read().strip().lower()
if editor_mode != (str(user_id)+u_id) and editor_mode != "":
    print("in editor mode",editor_mode,user_id)
    st.warning(" The system is currently in upload mode. Data uploads are disabled. Please try again later.")
elif editor_mode == "":
    st.warning(" Upload mode is off. Please enable Upload mode.")
else:
    # with open(r"C:\project_v2\simple-pay-v2\simple_pay\editor\v1.txt", "w") as f:
    #                 f.write(str(user_id))
    st.markdown(overlay_css, unsafe_allow_html=True)
    with tab1:
        if "processing" not in st.session_state:
            st.session_state.processing = False
        session = st
        file_type = st.selectbox("Select File Type", ["Disbursement", "Receipt", "Members", "Branch"])
        uploaded_file = st.file_uploader(f"Upload {file_type} CSV or Excel file", type=["csv", "xlsx"])
        if uploaded_file:
            ext = os.path.splitext(uploaded_file.name)[1].lower()
            df = None
            if ext == ".csv":
                try:
                    df = pd.read_csv(uploaded_file, encoding="utf-8")
                except UnicodeDecodeError:
                    raw_bytes = uploaded_file.getvalue()
                    result = chardet.detect(raw_bytes)
                    encoding = result["encoding"] or "utf-8"
                    df = pd.read_csv(pd.io.common.BytesIO(raw_bytes), encoding=encoding)

            elif ext in [".xlsx", ".xls"]:
                df = pd.read_excel(uploaded_file)
            else:
                st.error("Unsupported file format")
            # Cache the last Disbursement DF for Receipt validation fallback
            if uploaded_file and df is not None:
                if file_type == "Disbursement":
                    st.session_state["last_disbursement_df"] = df.copy()
            
    
        # st.dataframe(df)
        with st.spinner("Processing file... Please wait."):
            if uploaded_file is not None:
                # print( (not st.session_state.processing and "file_uploader" in st.session_state and st.session_state.file_uploader))
                st.session_state.processing = True
                temp_path = None
                databaseConnection = None
                # Editor_instance = Editor(user_id)
                try:
                    file_name = uploaded_file.name
                    databaseConnection = DatabaseConnection()
                    databaseConnection.connect()
                    cursor = databaseConnection.cursor
                    cursor.execute("SELECT 1 FROM file_hashes WHERE file_name = %s LIMIT 1", (file_name,))

                    if cursor.fetchone():
                        st.error(" This exact file has already been uploaded.")
                    else:
                    # if st.button("📄 Upload File"):
                    #     # with st.spinner("Processing file... Please wait."):
                            # is_valid, msg = validate_file(file_type, temp_path,df)
                    #         # if not is_valid:
                    #         #     st.error(f"⚠️ Validation failed: {msg}")
                    #         # else:
                    #             success, message = process(file_type, df,file_name)
                        
                        # db =None
                        # db.cursor.execute("""select edit_mode from editor""")
                        # result = db.cursor.fetchone()
                        total_amount, min_date, max_date = None, None, None
                        df = df
                        valid_df = validation(df, file_type=file_type)
                        if file_type == "Disbursement":
                            min_date = valid_df["Disb. Date"].min()
                            max_date = valid_df["Disb. Date"].max()
                            total_amount = valid_df["Amount Disbursed"].sum()
                        elif file_type == "Receipt":
                            min_date = valid_df["Receipt Date"].min()
                            max_date = valid_df["Receipt Date"].max()
                            total_amount = valid_df["Amount Received"].sum()
                        elif file_type == "Members":
                            min_date = valid_df["Disb. Date"].min()
                            max_date = valid_df["Disb. Date"].max()
                            total_amount = valid_df["Membership Income"].sum()
                        validate_result = get_data_from_validate_data(valid_df,min_date,max_date,file_type)
                        if validate_result != 0:
                            st.error(f" Data range overlaps with existing {file_type} data. Please check the date range.")
                            st.session_state.processing = False
                        # elif result[0] == 1:
                        #     st.error(" The system is currently in edit mode. Data uploads are disabled.")
                        else:
                            if st.button("📄 Upload File"):
                                # ✅ Run validation first
                                print("Uploading file...")
                                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                                    tmp.write(uploaded_file.getvalue())
                                    temp_path = tmp.name
                                
                                    # Build fallback only for Receipts
                                disb_df_fallback = st.session_state.get("last_disbursement_df") if file_type == "Receipt" else None
                                print("Uploading file...2")
                                valid_df, error_df, v_message, error_report_path = validate_file(
                                    file_type=file_type,
                                    file_path=temp_path,
                                    db_connection=databaseConnection,
                                    error_report_dir=ERROR_DIR,
                                    disbursement_df=disb_df_fallback,
                                )

                                if valid_df is None:
                                    st.error(f"⚠️ Validation failed: {v_message}")
                                else:
                                    insert_ok = False
                                    try:
                                        if file_type == "Disbursement":
                                            svc = DisbursementService(valid_df)
                                            svc.disbursement_insert_process()
                                            insert_ok = True

                                        elif file_type == "Receipt":
                                            svc = Reciept_service(valid_df)
                                            svc.reciept_insert_process()
                                            insert_ok = True

                                        elif file_type == "Members":
                                            if not valid_df.empty:
                                                # Drop unwanted columns if they exist
                                                EXCLUDE = {"Insert", "Error Reason", "Upload Status"}
                                                keep_df = valid_df.drop(columns=[c for c in EXCLUDE if c in valid_df.columns], errors="ignore")

                                                # Map uploaded CSV headers -> actual DB columns
                                                # Make sure these match exactly what comes from your CSV
                                                CSV_TO_DB = {
                                                    "Disb. Date": "disb_date",
                                                    "Borrower Name": "borrower_name",
                                                    "Branch": "branch",
                                                    "Membership Income": "membership_income",
                                                    "Transcode": "transcode"
                                                }

                                                #  Validate and reorder columns
                                                missing = [c for c in CSV_TO_DB if c not in keep_df.columns]
                                                if missing:
                                                    raise ValueError(f"Missing required columns in Members upload: {missing}")

                                                db_cols_order = list(CSV_TO_DB.values())
                                                df_for_load = keep_df[list(CSV_TO_DB.keys())].rename(columns=CSV_TO_DB)

                                                # Write to temp CSV (header kept for IGNORE 1 LINES)
                                                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8") as _tmp:
                                                    df_for_load.to_csv(_tmp.name, index=False)
                                                    tmp_csv = _tmp.name.replace("\\", "/")

                                                conn = None; cur = None
                                                try:
                                                    conn = DatabaseConnectionPool.get_connection()
                                                    cur = conn.cursor()

                                                    # Allow local infile
                                                    try:
                                                        cur.execute("SET SESSION local_infile = 1;")
                                                    except Exception:
                                                        pass

                                                    cols_sql = ", ".join(f"`{c}`" for c in db_cols_order)

                                                    #  Perform the actual load
                                                    sql = f"""
                                                        LOAD DATA LOCAL INFILE '{tmp_csv}'
                                                        INTO TABLE members
                                                        FIELDS TERMINATED BY ','
                                                        ENCLOSED BY '"'
                                                        LINES TERMINATED BY '\\r\\n'
                                                        IGNORE 1 LINES
                                                        ({cols_sql});
                                                    """
                                                    cur.execute(sql)
                                                    conn.commit()
                                                    insert_ok = True
                                                finally:
                                                    try: cur and cur.close()
                                                    except: pass
                                                    try: conn and conn.close()
                                                    except: pass
                                                    try: os.remove(tmp_csv)
                                                    except: pass

                                        elif file_type == "Branch":
                                            if not valid_df.empty:
                                                # 1️⃣ Drop unwanted columns safely
                                                EXCLUDE = {"Insert", "Error Reason", "Upload Status"}
                                                keep_df = valid_df.drop(columns=[c for c in EXCLUDE if c in valid_df.columns], errors="ignore")

                                                # 2️⃣ Normalize headers and find a column that matches 'branch'
                                                possible_branch_cols = [c for c in keep_df.columns if c.strip().lower() == "branch"]
                                                if not possible_branch_cols:
                                                    raise ValueError("No 'Branch' column found in the uploaded file.")

                                                branch_col = possible_branch_cols[0]
                                                df_for_load = keep_df[[branch_col]].rename(columns={branch_col: "branch"})

                                                # 3️⃣ Write to temp CSV (header kept for IGNORE 1 LINES)
                                                with tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8") as _tmp:
                                                    df_for_load.to_csv(_tmp.name, index=False)
                                                    tmp_csv = _tmp.name.replace("\\", "/")

                                                conn = None; cur = None
                                                try:
                                                    conn = DatabaseConnectionPool.get_connection()
                                                    cur = conn.cursor()

                                                    # Ensure LOCAL INFILE allowed
                                                    try:
                                                        cur.execute("SET SESSION local_infile = 1;")
                                                    except Exception:
                                                        pass

                                                    sql = f"""
                                                        LOAD DATA LOCAL INFILE '{tmp_csv}'
                                                        INTO TABLE branch
                                                        FIELDS TERMINATED BY ','
                                                        ENCLOSED BY '"'
                                                        LINES TERMINATED BY '\\r\\n'
                                                        IGNORE 1 LINES
                                                        (`branch`);
                                                    """
                                                    try:
                                                        cur.execute(sql)
                                                    except mysql.connector.Error as e:
                                                        # fallback to LF if CRLF fails
                                                        if "Incorrect integer value" in str(e) or "syntax" in str(e):
                                                            sql = sql.replace("\\r\\n", "\\n")
                                                            cur.execute(sql)
                                                        else:
                                                            raise

                                                    conn.commit()
                                                    insert_ok = True
                                                finally:
                                                    try: cur and cur.close()
                                                    except: pass
                                                    try: conn and conn.close()
                                                    except: pass
                                                    try: os.remove(tmp_csv)
                                                    except: pass

                                    except Exception as e:
                                        st.error(f"Insert error: {e}")
                                        insert_ok = False

                                    if insert_ok:
                                        # ----- writebacks that drive the UI -----
                                        # You already computed these above:
                                        #   file_type, file_name, valid_df, error_df, total_amount, min_date, max_date
                                        rows_ok  = len(valid_df) if valid_df is not None else 0
                                        rows_err = len(error_df) if error_df is not None else 0
                                        _upsert_file_status(
                                            file_type=file_type,
                                            last_filename=file_name,
                                            min_date=min_date,
                                            max_date=max_date,
                                            record_count=rows_ok + rows_err,
                                            total_amount=total_amount,
                                        )
                                        _insert_upload_summary(
                                            file_type=file_type,
                                            file_name=file_name,
                                            valid_df=valid_df,
                                            error_df=error_df,
                                            total_amount=total_amount,
                                            min_date=min_date,
                                            max_date=max_date,
                                        )
                                        # ----------------------------------------

                                        # Optional parquet refresh
                                        try:
                                            refresh_once(verbose=False, force=False)
                                            st.success("Uploaded successfully ")
                                        except Exception as e:
                                            st.success("Uploaded successfully")
                                            st.warning(f"Parquet refresh failed: {e}")
                                    else:
                                        st.error("Upload failed to insert. Check logs for details.")



                                    # Error report download (only if there are invalid rows)
                                    if error_df is not None and not error_df.empty:
                                        if error_report_path and os.path.exists(error_report_path):
                                            with open(error_report_path, "rb") as f:
                                                st.download_button(
                                                    label="⬇️ Download Error Report",
                                                    data=f,
                                                    file_name=os.path.basename(error_report_path),
                                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                                )
                                        else:
                                            buf = io.BytesIO()
                                            with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                                                error_df.to_excel(writer, index=False)
                                            buf.seek(0)
                                            st.download_button(
                                                label="⬇️ Download Error Report (inline)",
                                                data=buf,
                                                file_name=f"{file_type.lower()}_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                            )

                                    # with open(r"C:\project_v2\simple-pay-v2\simple_pay\editor\v1.txt", "w") as f:
                                    #     f.write("")
                                        # editor_mode = int(f.read().strip().lower())

                            # if success != "error":    
                            #     now = datetime.now()
                            #     record_count = len(valid_df) + len(error_df)
                            #     total_amount, min_date, max_date = None, None, None

                            #     if file_type == "Disbursement":
                            #         min_date = valid_df["Disb. Date"].min()
                            #         max_date = valid_df["Disb. Date"].max()
                            #         total_amount = valid_df["Amount Disbursed"].sum()
                            #     elif file_type == "Receipt":
                            #         min_date = valid_df["Receipt Date"].min()
                            #         max_date = valid_df["Receipt Date"].max()
                            #         total_amount = valid_df["Amount Received"].sum()
                            #     elif file_type == "Members":
                            #         min_date = valid_df["Disb. Date"].min()
                            #         max_date = valid_df["Disb. Date"].max()
                            #         total_amount = valid_df["Membership Income"].sum()

                            #     obj = {
                            #         "file_name": file_name,
                            #         "record_count": record_count,
                            #         "valid_rows": len(valid_df),
                            #         "error_rows": len(error_df),
                            #         "total_amount": total_amount,
                            #         # "min_date": min_date if min_date else None,
                            #         # "max_date": max_date if max_date else None,

                            #         "created_at": now.strftime("%Y-%m-%d %H:%M:%S")
                            #     }


                            #     summary_df = pd.DataFrame([obj])
                            #     summary_df.index = summary_df.index + 1
                            #     st.table(summary_df)
                            #     # Show download button if error file exists
                            #     # Show download button if error file exists (use returned path)
                            #     # --- DEBUG: see exactly why button might be hidden ---
                            #     # st.write("Debug:", {
                            #     #     "errors": int(len(error_df)),
                            #     #     "error_report_path": error_report_path,
                            #     #     "exists": (os.path.exists(error_report_path) if error_report_path else None),
                            #     #     "has_fallback_df": bool("last_disbursement_df" in st.session_state)
                            #     # })

                            #     # --- Prefer file download if writer created the file ---
                            #     if not error_df.empty and error_report_path and os.path.exists(error_report_path):
                            #         with open(error_report_path, "rb") as f:
                            #             st.download_button(
                            #                 label="⬇ Download Error Report",
                            #                 data=f,
                            #                 file_name=os.path.basename(error_report_path),
                            #                 mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            #             )
                            #     # --- Fallback: if file missing for any reason, still let the user download in-memory ---
                            #     elif not error_df.empty:
                            #         import io
                            #         buf = io.BytesIO()
                            #         with pd.ExcelWriter(buf, engine="openpyxl") as writer:
                            #             error_df.to_excel(writer, index=False)
                            #         buf.seek(0)
                            #         st.download_button(
                            #             label="⬇ Download Error Report (inline)",
                            #             data=buf,
                            #             file_name=f"{file_type.lower()}_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            #             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            #         )




                            #     st.session_state.processing = False
                            #     st.session_state.file_uploader = None
                            # else:
                            #     st.error(f" Upload failed: {message}")

                            
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    st.error(f" File handling error: {str(e)}")
                finally:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                    if databaseConnection:
                        databaseConnection.close()
                    st.session_state.processing = False
    # ------------------- Show permanent "Latest Uploads (static)" -------------------


        def _latest_uploads_df() -> pd.DataFrame:
            try:
                db = DatabaseConnection()
                db.connect()
                cur = db.cursor
                cur.execute("""
                    SELECT t.file_type, t.file_name, t.record_count, t.valid_rows, t.error_rows,
                        t.total_amount, t.min_date, t.max_date, t.created_at
                    FROM upload_summary t
                    JOIN (
                        SELECT file_type, MAX(created_at) AS mx
                        FROM upload_summary
                        GROUP BY file_type
                    ) m ON t.file_type = m.file_type AND t.created_at = m.mx
                    ORDER BY FIELD(t.file_type, 'Disbursement','Receipt','Members','Branch')
                """)
                rows = cur.fetchall()
                df = pd.DataFrame(rows, columns=[
                    "File Type","Filename","Records","Valid","Errors",
                    "Total Amount","Min Date","Max Date","Uploaded At"
                ])
                return df
            except Exception as e:
                st.error(f"Error fetching latest uploads: {e}")
                return pd.DataFrame()
            finally:
                try: cur and cur.close()
                except: pass
                try: db and db.close()
                except: pass

        st.subheader(" Summary table")
        static_df = _latest_uploads_df()
        if not static_df.empty:
            static_df.index = static_df.index + 1
            st.table(static_df)
        else:
            st.info("No upload history available.")



# ------------------- TAB 2: USER MANAGEMENT -------------------
with tab2:
    st.header("👤 User Management")
    with st.form("user_form"):
        st.subheader("➕ Create New User")
        new_username = st.text_input("Username", max_chars=50)
        new_password = st.text_input("Password", type="password", max_chars=100)
        user_role = st.selectbox("Role", ["employee", "admin"])

        if st.form_submit_button("Create User"):
            if not new_username or not new_password:
                st.error("Username and password are required.")
            elif len(new_username) < 4:
                st.error("Username must be at least 4 characters.")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                success, message = create_user(new_username.strip(), new_password, user_role)
                if success:
                    st.success(message)
                    time.sleep(0.3)
                    st.rerun()
                else:
                    st.error(message)

    st.subheader("📋 Existing Users")
    users = load_users()
    if users:
        df_users = pd.DataFrame(users, columns=["Username", "Role", "Created At"])
        df_users["Created At"] = df_users["Created At"].apply(
            lambda x: x.strftime("%Y-%m-%d") if isinstance(x, datetime) else str(x)
        )
        df_users["Password"] = "********"
        st.markdown("**User List with Actions:**")
        for i, row in df_users.iterrows():
            col1, col2, col3, col4, col5 = st.columns([3, 2, 3, 3, 2])
            col1.write(row["Username"])
            col2.write(row["Role"])
            col3.write(row["Created At"])
            col4.write(row["Password"])
            if row["Username"] != "admin":
                if col5.button("🗑️ Delete", key=f"delete_{row['Username']}"):
                    st.session_state["confirm_delete"] = row["Username"]
            else:
                col5.write("")
        if "confirm_delete" in st.session_state:
            uname = st.session_state["confirm_delete"]
            st.warning(f"⚠ Are you sure you want to delete user '**{uname}**'? This action cannot be undone.")
            c1, c2 = st.columns(2)
            if c1.button("✅ Yes, Delete"):
                success, message = delete_user(uname)
                if success:
                    st.success(message)
                    time.sleep(0.3)
                    del st.session_state["confirm_delete"]
                    st.rerun()
                else:
                    st.error(message)
                    del st.session_state["confirm_delete"]
            if c2.button("❌ Cancel"):
                del st.session_state["confirm_delete"]
    else:
        st.info("ℹ No users found.")
