from simple_pay.models.branch import BranchModel
from simple_pay.utils.database_connection import DatabaseConnection
from simple_pay.const import BRANCH

class BranchService:
    def __init__(self, df=None):
        self.df = df

    def branch_insert_process(self):
        try:
            db_connection = DatabaseConnection()
            db_connection.connect()
            db_connection.cursor = db_connection.conn.cursor()

            for _, row in self.df.iterrows():
                branch_data = BranchModel(
                    branch=row.get("Branch", "")
                ).dict()

                insert_query = f"""
                    INSERT IGNORE INTO {BRANCH} (branch, created_at)
                    VALUES (%(branch)s, %(created_at)s)
                """
                db_connection.cursor.execute(insert_query, branch_data)

            db_connection.conn.commit()
            db_connection.cursor.close()
            db_connection.close()
        except Exception as e:
            print(f"Error inserting branch data: {e}")
            raise e
