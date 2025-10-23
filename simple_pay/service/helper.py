from datetime import datetime, date
from dateutil import parser
from decimal import Decimal, InvalidOperation
import logging
import pandas as pd
from simple_pay.utils.database_connection import DatabaseConnection


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


    
@staticmethod
def to_decimal(value, default=Decimal("0.00")):
    try:
        if value is None or value == "":
            return default
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default

def verify_zero(dis,val1,val2):
    if dis[val1] <= 0 and dis[val2] <= 0:
        return False
    else:
        return True
   

@staticmethod
def calculate_status(dis,day_diff=0):
    if day_diff > 90:
        return "DEFAULT"
    if (dis["principal"] == dis["principal_paid"] and dis["interest"] == dis["interest_paid"] and verify_zero(dis,"principal","interest")) or \
        (dis["principal_30"] == dis["principal_30_paid"] and  dis["penalty_30"] == dis["penalty_30_paid"] and verify_zero(dis,"principal_30","penalty_30")) or \
            (dis["principal_45"] == dis["principal_45_paid"] and dis["penalty_45"] == dis["penalty_45_paid"] and verify_zero(dis,"principal_45","penalty_45")) or \
                (dis["principal_60"] == dis["principal_60_paid"] and dis["penalty_60"] == dis["penalty_60_paid"] and verify_zero(dis,"principal_60","penalty_60")):
        return "Closed"
    else:
        return "Active"

# @staticmethod
# def parse_date(val, fmt="%m-%d-%Y"):
#     if isinstance(val, date) and not isinstance(val, datetime):
#         return datetime.combine(val, datetime.min.time())
#     if isinstance(val, datetime):
#         return val
#     if isinstance(val, str):
#         try:
#             return datetime.strptime(val, fmt)
#         except ValueError as e:
#             import traceback
#             traceback.print_exc()
#             print(e)
#             try:
#                 return datetime.fromisoformat(val)
#             except Exception as e:
#                 import traceback
#                 traceback.print_exc()
#                 print(e)
#                 return None
#     return None

@staticmethod
def parse_date(val):
    if isinstance(val, date) and not isinstance(val, datetime):
        return datetime.combine(val, datetime.min.time())
    if isinstance(val, datetime):
        return val
    if isinstance(val, str):
        try:
            # Automatically parse various date formats
            return parser.parse(val)
        except (ValueError, TypeError) as e:
            import traceback
            traceback.print_exc()
            print(f"Could not parse date string: {val} -> {e}")
            return None
    return None

@staticmethod
def allocate_payment(
    days: int,
    amount_received: Decimal,
    interest: Decimal,
    penalty_30: Decimal,
    penalty_45: Decimal,
    penalty_60: Decimal,
    principal_30: Decimal,
    principal_45: Decimal,
    principal_60: Decimal,
) -> dict:
    remaining = amount_received
    paid = {
        "interest_paid": Decimal("0.00"),
        "penalty_30_paid": Decimal("0.00"),
        "penalty_45_paid": Decimal("0.00"),
        "penalty_60_paid": Decimal("0.00"),
        "principal_paid": Decimal("0.00"),
        "principal_30_paid": Decimal("0.00"),
        "principal_45_paid": Decimal("0.00"),
        "principal_60_paid": Decimal("0.00"),
        "excess": Decimal("0.00"),
    }

    if days <= 30:
        pay = min(remaining, interest)
        paid["interest_paid"] = pay
        remaining -= pay
        pay = remaining
        paid["principal_paid"] = pay
        remaining -= pay

    elif 31 <= days <= 45:
        pay = min(remaining, penalty_30)
        paid["penalty_30_paid"] = pay
        remaining -= pay
        pay = min(remaining, interest)
        paid["interest_paid"] = pay
        remaining -= pay
        pay = min(remaining, principal_30)
        paid["principal_30_paid"] = pay
        paid["principal_paid"] = pay
        remaining -= pay

    elif 46 <= days <= 60:
        pay = min(remaining, penalty_45)
        paid["penalty_45_paid"] = pay
        remaining -= pay
        pay = min(remaining, penalty_30)
        paid["penalty_30_paid"] = pay
        remaining -= pay
        pay = min(remaining, interest)
        paid["interest_paid"] = pay
        remaining -= pay
        pay = min(remaining, principal_45)
        paid["principal_45_paid"] = pay
        paid["principal_paid"] = pay
        remaining -= pay

    elif 61 <= days <= 90:
        pay = min(remaining, penalty_60)
        paid["penalty_60_paid"] = pay
        remaining -= pay
        pay = min(remaining, penalty_45)
        paid["penalty_45_paid"] = pay
        remaining -= pay
        pay = min(remaining, penalty_30)
        paid["penalty_30_paid"] = pay
        remaining -= pay
        pay = min(remaining, interest)
        paid["interest_paid"] = pay
        remaining -= pay
        pay = min(remaining, principal_60)
        paid["principal_60_paid"] = pay
        paid["principal_paid"] = pay
        remaining -= pay

    paid["excess"] = max(Decimal("0.00"), remaining)

    # logger.info(f"[DEBUG] Allocation Summary for Days={days} | Received={amount_received} → Paid: {paid}")
    return paid


def validation(df, file_type="Disbursement"):
    if df is None or df.empty:
        raise ValueError("DataFrame is empty or None")
    
    # print("df",df.dtypes)
    df.columns = df.columns.str.strip().str.replace("  ", " ")
    
    if file_type == "Disbursement":
        try:
            if df["Amount Disbursed"].dtype != "float64":
                df["Amount Disbursed"] = (
                        df["Amount Disbursed"]
                        .astype(str)                  # Make sure it's string
                        .str.strip()                  # Remove leading/trailing spaces
                        .str.replace(",", "")         # Remove commas
                        .replace("", "0")             # Replace empty string with 0
                        .astype(float)                # Convert to float
                    )
        except Exception as e:
            print(f"Error processing 'Amount Disbursed': {e}")
            raise Exception(f"Please check the file you are uploading.")
            
    if file_type == "Receipt":
        try:
            if df["Amount Received"].dtype != "float64":
                df["Amount Received"] = (
                        df["Amount Received"]
                        .astype(str)                  # Make sure it's string
                        .str.strip()                  # Remove leading/trailing spaces
                        .str.replace(",", "")         # Remove commas
                        .replace("", "0")
                        .replace("-", "0")            # Replace empty string with 0
                        .astype(float)                # Convert to float
                    )
        except Exception as e:
            print(f"Error processing 'Amount Disbursed': {e}")
            raise Exception(f"Please check the file you are uploading.")
        
    df = df.dropna(how="all")
    
    return df


def truncate_tables():
    try:
        db = DatabaseConnection()
        db.connect()
        cur = db.cursor

        # List of tables (adjust as needed)
        tables = ["disbursement", "receipt", "members", "branch","file_hashes","receipt_unresolved","upload_summary"]

        for table in tables:
            cur.execute(f"TRUNCATE TABLE {table};")
        cur.execute(f"""CREATE INDEX IF NOT EXISTS idx_loan_id
            ON disbursement (`loan_id`)""")

        db.conn.commit()
        db.close()
        return True, "All tables deleted successfully."
    except Exception as e:
        try:
            db.conn.rollback()
            db.close()
        except Exception:
            pass
        return False, f"Error truncating tables: {e}"


import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta

def robust_parse_datetimes_vectorized(series):
    """
    Vectorized parsing of mixed datetime-like values in a pd.Series.
    Returns (parsed_series, report_dict).
    Report contains failed indices and sample failed values.
    """

    s_orig = series
    # Preserve original index
    idx = s_orig.index

    # 0. If already datetime dtype, just convert and return quickly
    if pd.api.types.is_datetime64_any_dtype(s_orig):
        parsed = pd.to_datetime(s_orig, errors="coerce")
        report = {
            "total": len(s_orig),
            "parsed_ok": int((~parsed.isna()).sum()),
            "failed_count": int(parsed.isna().sum()),
            "failed_idx": parsed[parsed.isna()].index.tolist(),
            "failed_values": s_orig.loc[parsed.isna()].head(20).to_dict()
        }
        return parsed, report

    # 1. Convert bytes to str, keep NaNs untouched; convert non-strings to str for normalization
    # We create a cleaned string series for normalization but keep original for report
    s = s_orig.astype("object")  # ensure object dtype
    # Replace bytes
    mask_bytes = s.map(lambda x: isinstance(x, (bytes, bytearray)))
    if mask_bytes.any():
        s.loc[mask_bytes] = s.loc[mask_bytes].map(lambda b: b.decode("utf-8", "ignore"))

    # 2. Normalize strings: strip, remove NBSP/ZWSP, collapse whitespace, drop enclosing quotes
    # For non-strings leave as-is (numbers will be handled later)
    def _normalize_vectorized(ser):
        # Convert non-nulls to string for .str ops safely
        ser_str = ser.where(ser.isna(), ser.astype(str))
        # strip and replace NBSP/ZWSP/FEFF, collapse multiple whitespace
        ser_str = ser_str.str.strip()
        ser_str = ser_str.str.replace(r'[\u00A0\u200B\uFEFF]', ' ', regex=True)
        ser_str = ser_str.str.replace(r'\s+', ' ', regex=True)
        # remove enclosing quotes if present (both single and double)
        ser_str = ser_str.str.replace(r"^(['\"])(.*)\1$", r"\2", regex=True)
        # convert empty-string-like to NaN
        ser_str = ser_str.replace({'': None, 'None': None, 'nan': None, 'NaN': None}, regex=False)
        return ser_str

    s_clean = _normalize_vectorized(s)

    # 3. First fast pass: generic pd.to_datetime (vectorized)
    parsed = pd.to_datetime(s_clean, errors="coerce")

    # 4. Where parsed is NaT but original is not null, try dayfirst=True (vectorized)
    need = parsed.isna() & ~s_clean.isna()
    if need.any():
        parsed_dayfirst = pd.to_datetime(s_clean[need], errors="coerce", dayfirst=True)
        parsed.loc[need] = parsed_dayfirst

    # 5. Numeric-looking strings and numeric types: handle unix timestamps (s/ms) and Excel serials
    # Create numeric series for candidates where s_clean looks numeric
    looks_numeric = s_clean.str.fullmatch(r'[-+]?\d+(\.\d+)?') & ~s_clean.isna()
    # Also include numeric dtypes (int/float) from original
    numeric_mask_original = s_orig.map(lambda x: isinstance(x, (int, float, np.integer, np.floating)))
    numeric_candidates_mask = (looks_numeric | numeric_mask_original) & parsed.isna()

    if numeric_candidates_mask.any():
        # Convert to float safely
        numvals = pd.to_numeric(s_clean[numeric_candidates_mask], errors="coerce")
        # Heuristics:
        # - Unix seconds: numbers around 1e9..1e11 -> treat as seconds
        # - Unix milliseconds: around 1e12..1e15 -> treat as ms
        # - Excel serial days: small positive ints (1..80000) -> treat as Excel days
        # Build masks
        mask_seconds = numvals.between(1_000_000_000, 100_000_000_000)  # ~2001..5138 years (safe seconds range)
        mask_millis  = numvals.between(1_000_000_000_000, 10_000_000_000_000)  # ms
        mask_micros  = numvals.between(1_000_000_000_000_000, 10_000_000_000_000_000)  # us unlikely
        mask_excel   = numvals.between(1, 80000)  # Excel serial days roughly up to year ~2128
        # Apply conversions vectorized
        if mask_seconds.any():
            parsed.loc[numvals[mask_seconds].index] = pd.to_datetime(numvals[mask_seconds].astype(int), unit="s", errors="coerce")
        if mask_millis.any():
            parsed.loc[numvals[mask_millis].index] = pd.to_datetime(numvals[mask_millis].astype(int), unit="ms", errors="coerce")
        if mask_micros.any():
            parsed.loc[numvals[mask_micros].index] = pd.to_datetime(numvals[mask_micros].astype(int), unit="us", errors="coerce")
        if mask_excel.any():
            # Excel origin: 1899-12-30 is common for serials; create vectorized addition
            origin = pd.Timestamp("1899-12-30")
            excel_days = pd.to_timedelta(numvals[mask_excel].astype(int), unit="D")
            parsed.loc[numvals[mask_excel].index] = origin + excel_days

    # 6. For remaining NaT, try a few common explicit formats (vectorized application on mask)
    still_need = parsed.isna() & ~s_clean.isna()
    if still_need.any():
        # try these formats in order (vectorized). This avoids per-row python loops.
        formats_to_try = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d-%m-%Y %H:%M:%S",
            "%d-%m-%Y",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y",
            "%b %d, %Y",
            "%d %b %Y",
        ]
        for fmt in formats_to_try:
            cand_idx = s_clean[still_need].index
            if len(cand_idx) == 0:
                break
            # apply format parse only to the still-need slice
            parsed_try = pd.to_datetime(s_clean.loc[cand_idx], format=fmt, errors="coerce")
            # fill where parse succeeded
            success_idx = parsed_try.notna()
            if success_idx.any():
                parsed.loc[cand_idx[success_idx]] = parsed_try[success_idx]
            # recompute still_need
            still_need = parsed.isna() & ~s_clean.isna()
            if not still_need.any():
                break

    # 7. Final normalization: if any parsed values exist convert timezone-naive etc. (optional)
    parsed = pd.to_datetime(parsed, errors="coerce")  # ensure dtype unified

    # 8. Final report of failures
    failed_mask = parsed.isna() & ~s_clean.isna()
    failed_idx = parsed[failed_mask].index.tolist()
    report = {
        "total": int(len(s_orig)),
        "parsed_ok": int((~parsed.isna()).sum()),
        "failed_count": int(len(failed_idx)),
        "failed_idx": failed_idx,
        "failed_values": s_orig.loc[failed_idx].head(100).to_dict()  # sample of up to 100 failed
    }

    return parsed.reindex(idx), report
import os 
from simple_pay.utils.database_connection import DatabaseConnectionPool
def bulk_load( df, table_name):
        """Load a DataFrame into MySQL using LOAD DATA LOCAL INFILE."""
        if df is None or df.empty:
            return

        import tempfile
        db_connection = DatabaseConnectionPool.get_connection()
        cursor = None
        tmp_file = None
        try:
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
            df.to_csv(tmp_file.name, index=False, header=True)
            tmp_file.close()

            columns = ", ".join(df.columns)
            file_path = tmp_file.name.replace("\\", "/")
            query = f"""
                LOAD DATA LOCAL INFILE '{file_path}'
                INTO TABLE {table_name}
                FIELDS TERMINATED BY ',' 
                ENCLOSED BY '"'
                LINES TERMINATED BY '\\n'
                IGNORE 1 ROWS
                ({columns});
            """



            cursor = db_connection.cursor()
            cursor
            # print("cursor",cursor)
            cursor.execute(query)
            db_connection.commit()
            # print(f"✅ Loaded {len(df)} rows into {table_name}")

        except Exception as e:
            import traceback; traceback.print_exc()
            if db_connection:
                db_connection.rollback()
            raise e
        finally:
            if cursor:
                cursor.close()
            db_connection.close()
            if tmp_file:
                os.remove(tmp_file.name)
    
    
def get_data_from_validate_data(valid_df,min_date,max_date,file_type):
    db= None
    try:
        db = DatabaseConnection()
        db.connect()
        if isinstance(min_date, pd.Timestamp) or isinstance(min_date, datetime) or isinstance(min_date, date) or isinstance(min_date, np.datetime64):
            min_date = min_date.strftime("%Y-%m-%d")
            max_date = max_date.strftime("%Y-%m-%d")
        if file_type == "Disbursement":
            db.cursor.execute(f"Select count(*) from disbursement where disb_date >= '{min_date}' ")
            result = db.cursor.fetchall()
            # id_df = valid_df[["SUPERLENDER LOAN ID"]]
            # bulk_load(id_df, "disbursement")
            # db.cursor.execute(f"""CREATE TABLE IF NOT EXISTS  disbursement(
            #                         id INT AUTO_INCREMENT PRIMARY KEY,
            #                         loan_id VARCHAR(255) NOT NULL)""")
            # db.conn.commit()
            # db.cursor.execute(f"Select count(*) from disbursement inner join  where disb_date >= '{min_date}' ")
            # result = db.cursor.fetchall()
            return result[0][0]
        elif file_type == "Receipt":
            db.cursor.execute(f"Select count(*) from receipt where receipt_date >= '{min_date}' ")
            result = db.cursor.fetchall()
            return result[0][0]
            # id_df = valid_df["Loan ID"]
            # bulk_load(id_df, "disbursement")
        elif file_type == "Members":
            db.cursor.execute(f"Select count(*) from members where disb_date >= '{min_date}' ")
            result = db.cursor.fetchall()
            print("result",result)
            return result[0][0]
        else:
            return 0
    except Exception as e:
        print(e)
        return 1
    finally:
        try:
            if db:
                db.close()
        except Exception:
            pass
    # print("min_date",min_date,max_date)
    
    
    # print("result",result)
    # return result[0][0]
# service/helper.py

import pandas as pd
import traceback

def ehelper_get_latest_only(db_connection, types_order=None):
    """
    Fetch latest upload_summary rows for given types without inserting anything.
    Returns a pandas.DataFrame with one row per type in types_order.
    """
    if types_order is None:
        types_order = ["Disbursement", "Receipt", "Members"]

    try:
        fetch_latest_sql = f"""
            SELECT t.id, t.file_type, t.file_name, t.record_count, t.valid_rows, t.error_rows, t.total_amount,
                   t.min_date, t.max_date, t.created_at
            FROM upload_summary t
            JOIN (
                SELECT file_type, MAX(created_at) AS maxt
                FROM upload_summary
                WHERE file_type IN ({','.join(['%s']*len(types_order))})
                GROUP BY file_type
            ) m ON t.file_type = m.file_type AND t.created_at = m.maxt
        """
        db_connection.cursor.execute(fetch_latest_sql, tuple(types_order))
        latest_rows = db_connection.cursor.fetchall()
        rows_map = {row[1]: row for row in latest_rows} 

        display_rows = []
        for ttype in types_order:
            if ttype in rows_map:
                row = rows_map[ttype]
                display_rows.append({
                    "Type": row[1],
                    "File Name": row[2],
                    "Records": row[3],
                    "Valid": row[4],
                    "Errors": row[5],
                    "Total Amount": row[6] if row[6] is not None else "",
                    # "Min Date": str(row[7]) if row[7] else "",
                    # "Max Date": str(row[8]) if row[8] else "",
                    "Uploaded At": str(row[9]) if row[9] else ""
                })
            else:
                display_rows.append({
                    "Type": ttype,
                    "File Name": "",
                    "Records": 0,
                    "Valid": 0,
                    "Errors": 0,
                    "Total Amount": "",
                    # "Min Date": "",
                    # "Max Date": "",
                    "Uploaded At": ""
                })

        return pd.DataFrame(display_rows)
    except Exception:
        traceback.print_exc()
        return pd.DataFrame({"Type": [], "File Name": [], "Records": [], "Valid": [], "Errors": [], "Total Amount": [], "Min Date": [], "Max Date": [], "Uploaded At": []})


# utils/currency_pref.py
import mysql.connector
import streamlit as st

def _get_conn():
    # use your secrets/ENV
    return mysql.connector.connect(
        host="localhost", user="root", password="", database="keny", autocommit=True
    )

@st.cache_data(ttl=60)  # avoid hitting DB on every rerun; refreshes each minute
def get_selected_currency_code() -> str | None:
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT selected_currency_code FROM app_settings WHERE id=1;")
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        try: cur.close()
        except: pass
        conn.close()

@st.cache_data(ttl=60)
def get_currency_name_by_code(code: str) -> str | None:
    if not code:
        return None
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM currency WHERE code=%s;", (code,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        try: cur.close()
        except: pass
        conn.close()

def get_selected_currency_name() -> str | None:
    code = get_selected_currency_code()
    return get_currency_name_by_code(code) if code else None

def clear_currency_cache():
    # Call this after you SAVE in the sidebar so report reads the latest immediately
    get_selected_currency_code.clear()   # type: ignore[attr-defined]
    get_currency_name_by_code.clear()    # type: ignore[attr-defined]




class Editor:
    def __init__(self,user_id):
        self.user_id = user_id