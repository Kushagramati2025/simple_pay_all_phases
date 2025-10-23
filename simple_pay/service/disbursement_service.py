import os
import time
from datetime import datetime, date

import pandas as pd
from dateutil import parser
from sqlalchemy.exc import OperationalError, InterfaceError

from simple_pay.utils.database_connection import DatabaseConnection
from simple_pay.service.helper import validation  # kept if you still want basic column checks
from simple_pay.const import DISBURSMENT

import logging
logger = logging.getLogger(__name__)

# =============================================================================
#  Robust retry helpers for transient MySQL disconnects
# =============================================================================
RETRY_ERRNOS = {2006, 2013, 2055}  # gone away / lost connection / socket reset
RETRY_MSG_MARKERS = (
    "lost connection to mysql server",
    "mysql server has gone away",
    "lost connection during query",
    "this connection is closed",
    "connection reset by peer",
    "broken pipe",
    "read timeout",
    "write timeout",
)

def _is_retryable_sql_error(exc: Exception) -> bool:
    orig = getattr(exc, "orig", None) or exc
    errno = getattr(orig, "errno", None)
    if isinstance(errno, int) and errno in RETRY_ERRNOS:
        return True
    if hasattr(orig, "args") and orig.args:
        try:
            if int(orig.args[0]) in RETRY_ERRNOS:
                return True
        except Exception:
            pass
    msg = str(orig).lower()
    return any(m in msg for m in RETRY_MSG_MARKERS)

def run_with_retry(engine, fn, max_retries=3, sleep_secs=1.0, *args, **kwargs):
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except (OperationalError, InterfaceError) as e:
            if _is_retryable_sql_error(e) and attempt < max_retries:
                attempt += 1
                try:
                    engine.dispose()  # drop stale sockets
                except Exception:
                    pass
                time.sleep(sleep_secs)
                continue
            raise


# =============================================================================
#  DisbursementService (INSERT-ONLY, minimal 6 columns)
# =============================================================================
class DisbursementService:
    """
    Upload → MySQL (insert-only).
    Keeps ONLY these columns:
      loan_id, disb_date, borrower_name, branch, transcode, principal

    All reads/updates/view logic removed. No post-commit calculations.
    """

    def __init__(self, df: pd.DataFrame | None = None):
        self.df = df

    # ---------- Optional utility for ad-hoc row mapping ----------
    def convert_to_standard_date(self, raw_date):
        """Parse into YYYY-MM-DD (date-only)."""
        try:
            if isinstance(raw_date, str):
                parsed_date = parser.parse(raw_date)
            elif isinstance(raw_date, date):
                parsed_date = raw_date
            else:
                return None
            return parsed_date.strftime("%Y-%m-%d")
        except Exception:
            import traceback
            traceback.print_exc()
            return None

    def process(self, row: dict) -> dict:
        """
        Map a single upload row → minimal schema (6 columns).
        No calculations.
        """
        try:
            raw_date = row["Disb. Date"] if "Disb. Date" in row else row["disb_date"]
            # Normalize date to YYYY-MM-DD
            if isinstance(raw_date, str):
                # try dd-mm-yyyy → yyyy-mm-dd → mm-dd-yyyy
                try:
                    disb = datetime.strptime(raw_date, "%d-%m-%Y")
                except Exception:
                    try:
                        disb = datetime.strptime(raw_date, "%Y-%m-%d")
                    except Exception:
                        disb = datetime.strptime(raw_date, "%m-%d-%Y")
                disb_date = disb.strftime("%Y-%m-%d")
            elif isinstance(raw_date, date):
                disb_date = raw_date.strftime("%Y-%m-%d")
            else:
                disb_date = None

            return {
                "loan_id":       str(row["SUPERLENDER LOAN ID"] if "SUPERLENDER LOAN ID" in row else row["loan_id"]),
                "disb_date":     disb_date,
                "borrower_name": row.get("Borrower Name", ""),
                "branch":        row.get("Branch", ""),
                "transcode":     row.get("Transcode", ""),
                "principal":     float(row.get("Amount Disbursed", row.get("principal", 0)) or 0),
            }
        except Exception as e:
            import traceback; traceback.print_exc()
            raise e

    # ---------- Chunked insert (DataFrame → MySQL) ----------
        # ---------- Chunked insert (DataFrame → MySQL) ----------
    def insert_chunk(self, chunk: pd.DataFrame):
        """
        Insert a ready DataFrame chunk containing ONLY:
          loan_id, disb_date, borrower_name, branch, transcode, principal, amount_disbursed
        into DISBURSMENT (main table only).
        """
        db_connection = DatabaseConnection()
        db_connection.connect()
        try:
            if chunk is None or len(chunk) == 0:
                return

            required_cols = [
                "loan_id", "disb_date", "borrower_name",
                "branch", "transcode", "principal", "amount_disbursed"
            ]
            missing = [c for c in required_cols if c not in chunk.columns]
            if missing:
                raise ValueError(f"insert_chunk: missing required columns: {missing}")

            chunk = chunk[required_cols].copy()

            columns = ", ".join(required_cols)
            placeholders = ", ".join(["%s"] * len(required_cols))

            insert_main = f"INSERT INTO {DISBURSMENT} ({columns}) VALUES ({placeholders})"

            db_connection.cursor.executemany(insert_main, [tuple(row) for row in chunk.to_numpy()])
            db_connection.conn.commit()

        except Exception:
            if getattr(db_connection, "conn", None):
                try:
                    db_connection.conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            try:
                if getattr(db_connection, "cursor", None):
                    db_connection.cursor.close()
            finally:
                db_connection.close()


    # ---------- Fast bulk load with retry ----------
    def disbursement_insert_process(self, chunk_size: int = 10000, use_load_data: bool = False, max_retries: int = 3):
        """
        Vectorized clean-up and bulk insert into DISBURSMENT.
        Only the 6 minimal columns are written.
        """
        if self.df is None or self.df.empty:
            return

        # 1) BASIC VALIDATION (optional)
        df = self.df.copy()
        try:
            df = validation(df, "Disbursement")
        except Exception:
            logger.exception("validation() failed; continuing with raw frame")

        # 2) DATE NORMALIZATION
        raw_date_col = "Disb. Date" if "Disb. Date" in df.columns else "disb_date"
        s1 = pd.to_datetime(df.get(raw_date_col), format="%d-%m-%Y", errors="coerce")
        s2 = pd.to_datetime(df.get(raw_date_col), format="%Y-%m-%d", errors="coerce")
        s3 = pd.to_datetime(df.get(raw_date_col), format="%m-%d-%Y", errors="coerce")
        disb_dt = s1.fillna(s2).fillna(s3)
        df["disb_date"] = disb_dt.dt.strftime("%Y-%m-%d")

        # 3) BUILD MINIMAL OUTPUT
        def pick(*keys, default=None):
            for k in keys:
                if k in df.columns:
                    return df[k]
            return pd.Series([default] * len(df), index=df.index)

        def col_or(frame: pd.DataFrame, col: str, default=""):
            return frame[col] if col in frame.columns else pd.Series([default] * len(frame), index=frame.index)

        df_out = pd.DataFrame({
            "loan_id":       pick("SUPERLENDER LOAN ID", "loan_id").astype(str),
            "disb_date":     df["disb_date"],
            "borrower_name": col_or(df, "Borrower Name", ""),
            "branch":        col_or(df, "Branch", ""),
            "transcode":     col_or(df, "Transcode", ""),
            "principal":     pick("Amount Disbursed", "principal", default=0).fillna(0).astype(float),
            "amount_disbursed": pick("Amount Disbursed", "amount_disbursed", default=0).fillna(0).astype(float),
        })

        df_out = df_out[df_out["loan_id"].astype(str).str.len() > 0]
        df_out = df_out[df_out["disb_date"].astype(str).str.len() > 0]

        if df_out.empty:
            return

        db = DatabaseConnection()
        db.create_engine()
        engine = db.engine

        if use_load_data:
            tmp_path = os.path.join("C:\\", "disb_load.csv") if os.name == "nt" else os.path.join("/tmp", "disb_load.csv")
            df_out.to_csv(tmp_path, index=False, lineterminator="\n")
            path_for_sql = tmp_path.replace("\\", "/")
            cols = ",".join(df_out.columns)

            load_sql_main = (
                f"LOAD DATA LOCAL INFILE '{path_for_sql}' "
                f"INTO TABLE {DISBURSMENT} "
                "FIELDS TERMINATED BY ',' ENCLOSED BY '\"' "
                "LINES TERMINATED BY '\\n' "
                "IGNORE 1 LINES "
                f"({cols})"
            )

            def _load(sql):
                raw = engine.raw_connection()
                try:
                    cur = raw.cursor()
                    cur.execute(sql)
                    raw.commit()
                finally:
                    try:
                        cur.close()
                    finally:
                        raw.close()

            run_with_retry(engine, _load, max_retries=max_retries, sql=load_sql_main)
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        else:
            def _append(table_name: str):
                with engine.begin() as conn:
                    df_out.to_sql(
                        table_name,
                        con=conn,
                        if_exists="append",
                        index=False,
                        method="multi",
                        chunksize=min(chunk_size, 1000),
                    )

            run_with_retry(engine, _append, max_retries=max_retries, table_name=DISBURSMENT)
