
from simple_pay.service.disbursement_service import DisbursementService
from simple_pay.service.reciept_service import Reciept_service
from simple_pay.service.membership import Membership_service
from simple_pay.service.branch import BranchService
import pandas as pd
from simple_pay.utils.database_connection import DatabaseConnection
from datetime import datetime
from simple_pay.utils.validation import compute_file_hash
import chardet

@staticmethod
def process(file_type, valid_df, error_df, file_name):
    databaseConnection = DatabaseConnection()
    databaseConnection.connect()
    
    try:
        # Check duplicate
        databaseConnection.cursor.execute("SELECT file_hash FROM file_hashes WHERE file_hash = %s", (file_name,))
        result = databaseConnection.cursor.fetchall()
        if len(result) > 0:
            return "error", f"File {file_name} already exists in the database. Please upload a different file."
        
        # Insert data into correct table
        if file_type == "Disbursement":
            DisbursementService(valid_df).disbursement_insert_process()
            min_date = valid_df["Disb. Date"].min()
            max_date = valid_df["Disb. Date"].max()
            total_amount = valid_df["Amount Disbursed"].sum()
        elif file_type == "Receipt":
            Reciept_service(valid_df).reciept_insert_process()
            min_date = valid_df["Receipt Date"].min()
            max_date = valid_df["Receipt Date"].max()
            total_amount = valid_df["Amount Received"].sum()
        elif file_type == "Members":
            print("4.1")
            Membership_service(valid_df).membership_insert_process()
            print("4.2")
            min_date = valid_df["Disb. Date"].min()
            max_date = valid_df["Disb. Date"].max()
            total_amount = valid_df["Membership Income"].sum()
        elif file_type == "Branch":
            BranchService(valid_df).branch_insert_process()
            min_date = max_date = total_amount = None
        
        now = datetime.now()

        # Convert to Python native types
        record_count = int(len(valid_df) + len(error_df))
        valid_rows = int(len(valid_df))
        error_rows = int(len(error_df))
        total_amount = float(total_amount) if total_amount is not None else None

        def safe_date(val):
            if val is None or pd.isna(val):
                return None
            if hasattr(val, "to_pydatetime"):   # Pandas Timestamp
                return val.to_pydatetime().date()
            return str(val)  # already string

        min_date = safe_date(min_date)
        max_date = safe_date(max_date)

        # Insert into upload_summary
        # Insert into upload_summary
        databaseConnection.cursor.execute("""
            INSERT INTO upload_summary 
            (file_name, record_count, valid_rows, error_rows, total_amount, min_date, max_date, created_at, file_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            str(file_name),
            record_count,
            valid_rows,
            error_rows,
            total_amount,
            min_date,
            max_date,
            now.strftime("%Y-%m-%d %H:%M:%S"),
            file_type   
        ))

        # Track file hash
        databaseConnection.cursor.execute("""
            INSERT INTO file_hashes (file_name, file_hash, last_upload)
            VALUES (%s, %s, %s)
        """, (file_type, str(file_name), now.strftime("%Y-%m-%d %H:%M:%S")))

        databaseConnection.conn.commit()
        return "success", f"{file_type} records processed successfully"

    except Exception as e:
        import traceback
        traceback.print_exc()
        databaseConnection.conn.rollback()
        return "error", f"Failed to process {file_type} records: {str(e)}"
    finally:
        databaseConnection.close()

