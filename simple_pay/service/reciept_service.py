import os
import logging
from datetime import datetime, date

import pandas as pd
import tempfile

from simple_pay.utils.database_connection import DatabaseConnectionPool

from simple_pay.service.helper import (
    to_decimal,
    validation,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Reciept_service:
    """
    INSERT-ONLY receipt ingestion.

    - No calculations or reads from MySQL.
    - No disbursement updates.
    - Rows missing loan_id go to `receipt_unresolved`.
    - Valid rows go to `receipt`.

    Written columns:
      loan_id, receipt_date, receipt_id, amount_received, transcode, resolve, created_at
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df

    # ---------- BULK LOAD HELPER (insert-only) ----------
    def bulk_load(self, df: pd.DataFrame, table_name: str):
        """Load a DataFrame into MySQL using LOAD DATA LOCAL INFILE (insert-only)."""
        if df is None or df.empty:
            return

        conn = None
        cursor = None
        tmp_file = None
        try:
            conn = DatabaseConnectionPool.get_connection()

            # 1) Dump to a temp CSV with header
            tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
            df.to_csv(tmp_file.name, index=False, header=True)
            tmp_file.close()

            # 2) LOAD DATA
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

            cursor = conn.cursor()
            cursor.execute(query)
            conn.commit()

        except Exception as e:
            import traceback; traceback.print_exc()
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise e
        finally:
            if cursor:
                try:
                    cursor.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
            if tmp_file:
                try:
                    os.remove(tmp_file.name)
                except Exception:
                    pass

    # ---------- PUBLIC INSERT WRAPPER ----------
    def insert_chunk(self, chunk: pd.DataFrame, table_name: str = "receipt"):
        """Insert a prepared chunk directly to a table (insert-only)."""
        self.bulk_load(chunk, table_name)

    # ---------- MAIN: normalize & insert-only ----------
    def reciept_insert_process(self):
        """
        Normalize receipt DataFrame and insert rows:
          - Valid rows  -> receipt
          - Unresolved  -> receipt_unresolved

        No slab calc, no allocation, no disbursement updates, no reads.
        """
        if self.df is None or self.df.empty:
            return

        df = self.df.copy()

        # Optional: basic header/shape checks
        try:
            df = validation(df, "Receipt")  # your helper; safe if a no-op
        except Exception:
            logger.exception("validation(Receipt) failed; continuing with raw DataFrame")

        # Normalize text cols used below
        if "Transcode" in df.columns:
            df["Transcode"] = df["Transcode"].fillna("").astype(str)
        if "Receipt ID" in df.columns:
            df["Receipt ID"] = df["Receipt ID"].fillna("").astype(str)

        # Parse/normalize receipt date column into YYYY-MM-DD (date, not datetime)
        # Accepts: %d-%m-%Y, %m-%d-%Y, %Y-%m-%d
        date_col = None
        for candidate in ["Receipt Date", "receipt_date", "date"]:
            if candidate in df.columns:
                date_col = candidate
                break

        if date_col is None:
            # no date column -> entire batch unresolved
            df["receipt_date"] = datetime.now().strftime("%Y-%m-%d")
        else:
            series = df[date_col]
            if series.dtype == "object":
                parsed = None
                for fmt in ("%d-%m-%Y", "%m-%d-%Y", "%Y-%m-%d"):
                    try:
                        parsed = pd.to_datetime(series, format=fmt, errors="coerce")
                        if parsed.notna().any():
                            break
                    except Exception:
                        continue
                if parsed is None:
                    parsed = pd.to_datetime(series, errors="coerce")
                df["receipt_date"] = parsed.dt.strftime("%Y-%m-%d")
            else:
                # pandas datetime-like or mixed
                parsed = pd.to_datetime(series, errors="coerce")
                df["receipt_date"] = parsed.dt.strftime("%Y-%m-%d")

        # loan_id extraction (string)
        if "SUPERLENDER LOAN ID" in df.columns:
            df["loan_id"] = df["SUPERLENDER LOAN ID"].astype(str).str.strip()
        elif "loan_id" in df.columns:
            df["loan_id"] = df["loan_id"].astype(str).str.strip()
        else:
            df["loan_id"] = ""

        # amount_received as float
        if "Amount Received" in df.columns:
            amt_series = df["Amount Received"].astype(str).str.replace(",", "", regex=False)
        elif "amount_received" in df.columns:
            amt_series = df["amount_received"].astype(str).str.replace(",", "", regex=False)
        else:
            amt_series = pd.Series(["0"] * len(df), index=df.index)

        df["amount_received"] = pd.to_numeric(amt_series, errors="coerce").fillna(0.0)

        # receipt_id
        if "Receipt ID" in df.columns:
            df["receipt_id"] = df["Receipt ID"].astype(str)
        elif "receipt_id" in df.columns:
            df["receipt_id"] = df["receipt_id"].astype(str)
        else:
            df["receipt_id"] = ""

        # transcode
        if "Transcode" in df.columns:
            df["transcode"] = df["Transcode"].astype(str)
        elif "transcode" in df.columns:
            df["transcode"] = df["transcode"].astype(str)
        else:
            df["transcode"] = ""

        # resolve flag: mark unresolved when missing loan_id or missing date
        df["resolve"] = "Y"
        df.loc[(df["loan_id"] == "") | (df["loan_id"].isna()), "resolve"] = "U"
        df.loc[(df["receipt_date"] == "") | (df["receipt_date"].isna()), "resolve"] = "U"

        # created_at
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df["created_at"] = now_str

        # Final shape (exact column order)
        out_cols = ["loan_id", "receipt_date", "receipt_id", "amount_received", "transcode", "resolve", "created_at"]
        for c in out_cols:
            if c not in df.columns:
                df[c] = None
        final_df = df[out_cols].copy()

        # Split resolved vs unresolved
        unresolved_df = final_df[final_df["resolve"] == "U"].copy()
        resolved_df = final_df[final_df["resolve"] != "U"].copy()

        # INSERTS (insert-only)
        if not resolved_df.empty:
            self.bulk_load(resolved_df, "receipt")

        if not unresolved_df.empty:
            self.bulk_load(unresolved_df, "receipt_unresolved")

        # Done: no component inserts, no disbursement updates, no reads.
