import pandas as pd
import chardet
import hashlib
from datetime import datetime
from decimal import Decimal
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TABLE_SCHEMAS = {
    "Disbursement": {
        "columns": ["Disb. Date", "SUPERLENDER LOAN ID", "Borrower Name", "Branch", "Disbursement ID", "Amount Disbursed", "Transcode"],
        "critical": ["Disb. Date", "SUPERLENDER LOAN ID", "Amount Disbursed"]
    },
    "Receipt": {
        "columns": ["Receipt Date", "SUPERLENDER LOAN ID", "Receipt ID", "Amount Received", "Transcode"],
        "critical": ["Receipt Date", "SUPERLENDER LOAN ID", "Amount Received"]
    },
    "Members": {
        "columns": ["Disb. Date", "Borrower Name", "Branch", "Membership Income", "Transcode"],
        "critical": ["Disb. Date", "Membership Income"]
    },
    "Branch": {
        "columns": ["Branch"],
        "critical": ["Branch"]  # treat Branch as critical, cannot be blank
    }
}

def compute_file_hash(file_path, algorithm='sha256'):
    hasher = hashlib.new(algorithm)
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()

def is_duplicate_file(file_path, db_connection):
    """Check if file with same content already uploaded using hash"""
    file_hash = compute_file_hash(file_path)
    cursor = db_connection.cursor
    cursor.execute("SELECT COUNT(*) FROM file_hashes WHERE file_hash = %s", (file_hash,))
    count = cursor.fetchone()[0]

    if count > 0:
        return True, file_hash
    else:
        cursor.execute(
            "INSERT INTO file_hashes (file_hash, file_name, last_upload) VALUES (%s, %s, NOW())",
            (file_hash, os.path.basename(file_path))
        )
        db_connection.conn.commit()
        return False, file_hash


def validate_file(file_type, file_path, db_connection, error_report_dir="error_reports",disbursement_df = None):
    try:
        # 🔎 Duplicate check
        is_dup, file_hash = is_duplicate_file(file_path, db_connection)
        if is_dup:
            logging.warning(f"Duplicate file skipped: {file_path}")
            return None, None, f"Duplicate file upload detected (hash: {file_hash})", None

        schema = TABLE_SCHEMAS[file_type]

        # Detect extension + read EVERYTHING as string (stable parsing)
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".csv":
            try:
                df = pd.read_csv(file_path, encoding="utf-8", thousands=",", dtype=str, low_memory=False)
            except UnicodeDecodeError:
                with open(file_path, "rb") as f:
                    result = chardet.detect(f.read())
                encoding = result["encoding"] or "utf-8"
                df = pd.read_csv(file_path, encoding=encoding, thousands=",", dtype=str, low_memory=False)
        elif ext in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path, dtype=str)
        else:
            return None, None, f"Unsupported file format: {ext}", None

        # --- Column Cleaning ---
        def clean_column_name(col: str) -> str:
            cleaned = " ".join(col.strip().split())   # trim + collapse internal spaces
            return cleaned.title()                    # Title Case

        df.columns = [clean_column_name(col) for col in df.columns]
        expected_columns  = [clean_column_name(c) for c in schema["columns"]]
        expected_critical = [clean_column_name(c) for c in schema["critical"]]

        # ✅ schema presence check
        missing_cols = [col for col in expected_columns if col not in df.columns]
        if missing_cols:
            return None, pd.DataFrame(), f"Missing columns: {', '.join(missing_cols)}", None

        # --- Vectorized Validations ---
        df = df.copy()

        # Trim whitespace in all string cells (apply+map; avoids applymap deprecation)
        df = df.apply(lambda col: col.map(lambda x: x.strip() if isinstance(x, str) else x))

        # Default flags
        df["Insert"] = "Yes"
        df["Error Reason"] = ""

        # Critical not-null
        for col in expected_critical:
            mask_missing = df[col].isna() | (df[col].astype(str).str.strip() == "")
            df.loc[mask_missing, "Error Reason"] += f"Missing {col}; "
            df.loc[mask_missing, "Insert"] = "No"

        # Date validation (handles 'Disb. Date' and 'Receipt Date')
        for col in [c for c in expected_critical if "date" in c.lower()]:
            cleaned_vals = (
                df[col]
                .astype(str)
                .str.strip()
                .replace({"": None, "nan": None, "NaN": None})
            )
            from simple_pay.service.helper import robust_parse_datetimes_vectorized
            # print("cleaned val------------------", cleaned_vals)
            parsed,report = robust_parse_datetimes_vectorized(cleaned_vals)
            
            # parsed = pd.to_datetime(
            #     cleaned_vals,
            #     errors="coerce",
            #     dayfirst=True,                # supports dd-mm-yyyy
                
            # )
            # infer_datetime_format=True
            # print("error handiling___________________",parsed)
            mask_invalid = parsed.isna()
            df.loc[mask_invalid, "Error Reason"] += f"Invalid {col}; "
            df.loc[mask_invalid, "Insert"] = "No"
            # only overwrite valid rows
            df.loc[~mask_invalid, col] = parsed[~mask_invalid].dt.strftime("%Y-%m-%d")

        # Amount/Income validation
        for col in [c for c in expected_critical if ("Amount" in c or "Income" in c)]:
            df[col] = df[col].astype(str).str.replace(",", "", regex=True)
            mask_invalid = ~df[col].str.match(r"^\d+(\.\d+)?$")
            df.loc[mask_invalid, "Error Reason"] += f"Invalid {col}; "
            df.loc[mask_invalid, "Insert"] = "No"
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Non-critical presence (log only)
        for col in expected_columns:
            if col not in expected_critical:
                mask_missing = df[col].isna() | (df[col].astype(str).str.strip() == "")
                df.loc[mask_missing, "Error Reason"] += f"Missing {col}; "

        # Upload status
        df["Upload Status"] = df["Insert"].map(lambda x: "Inserted" if x == "Yes" else "Skipped")

        # Split
        error_df = df[df["Upload Status"] == "Skipped"].copy()
        valid_df = df[df["Upload Status"] == "Inserted"].copy()

        # --- Map cleaned column names back to original schema names ---
        col_map = {clean_column_name(c): c for c in schema["columns"]}
        valid_df.rename(columns=col_map, inplace=True)
        error_df.rename(columns=col_map, inplace=True)

        # --- Save error report with an absolute, unique path & RETURN it ---
        error_report_path = None
        error_report_dir_abs = os.path.abspath(error_report_dir)
        os.makedirs(error_report_dir_abs, exist_ok=True)

        if not error_df.empty:
            base = os.path.splitext(os.path.basename(file_path))[0]
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            fname = f"{file_type.lower()}_{base}_errors_{ts}.xlsx"
            error_report_path = os.path.join(error_report_dir_abs, fname)

            # safe write
            with pd.ExcelWriter(error_report_path, engine="openpyxl") as writer:
                error_df.to_excel(writer, index=False)

            logging.info(f"Error report saved: {error_report_path}")

        return valid_df, error_df, "Validation completed", error_report_path

    except FileNotFoundError:
        return None, None, f"File not found: {file_path}", None
    except pd.errors.ParserError:
        return None, None, f"Invalid file format in file: {file_path}", None
    except Exception as e:
        return None, None, f"Validation error: {str(e)}", None

