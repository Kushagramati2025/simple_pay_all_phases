from simple_pay.models.members import MemebersModel
from simple_pay.utils.database_connection import DatabaseConnection
from datetime import datetime, date
from simple_pay.service.helper import  parse_date
import pandas as pd
class Membership_service:
    def __init__(self, df=None):
        self.df = df
 
    def membership_insert_process(self):
        try:
            # db_connection = DatabaseConnection()
            # db_connection.connect()
            # db_connection.cursor = db_connection.conn.cursor()
            data_list = []
            for _, row in self.df.iterrows():
                # Convert Disb. Date
                raw_date = row["Disb. Date"]
                # if isinstance(raw_date, str):
                #     converted_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
                # elif isinstance(raw_date, date):
                #     converted_date = raw_date.strftime("%Y-%m-%d")
                # else:
                #     converted_date = None
                converted_date = parse_date(raw_date).strftime("%Y-%m-%d")
 
                member_data = MemebersModel(
                    Disb_Date=converted_date,
                    Borrower_Name=row.get("Borrower Name", ""),
                    Branch=row.get("Branch", ""),
                    Membership_Income=row.get("Membership Income", 0.0),
                    Transcode=row.get("Transcode", "")
                ).dict()
 
                data_list.append(member_data)
            processed_df = pd.DataFrame(data_list)
            db_connection = DatabaseConnection()
            db_connection.create_engine()
            processed_df.to_sql(
                "members",
                con=db_connection.engine,
                if_exists="replace",  # or "append"
                index=False,
                method="multi",
                chunksize=50000
            )
               
                # insert_query = """
                #     INSERT INTO members (
                #         disb_date, borrower_name, branch,
                #         membership_income, transcode, created_at
                #     ) VALUES (
                #         %(Disb_Date)s, %(Borrower_Name)s, %(Branch)s,
                #         %(Membership_Income)s, %(Transcode)s, %(created_at)s
                #     )
                # """
 
            #     db_connection.cursor.execute(insert_query, member_data)
 
            # db_connection.conn.commit()
            # db_connection.cursor.close()
            # db_connection.close()
        except Exception as e:
            print(f"Error inserting membership data: {e}")
            raise e