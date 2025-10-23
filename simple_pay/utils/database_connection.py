  
import mysql.connector
import mysql.connector.pooling
from mysql.connector import errorcode
from simple_pay.const import *
from mysql.connector import Error as MySQLError

class DatabaseConnectionPool:
    """
    Central MySQL connection pool for mysql-connector.
    Key hardening:
      - pool_reset_session=True to clear server session state on reuse
      - conn.consume_results() on checkout to clear any leftover results on this socket
      - ping(reconnect=True) to ensure the socket is alive
    """
    _pool = None  # singleton
    _cfg = None

    @classmethod
    def init_pool(cls, **overrides):
        """
        Call this once at app startup (e.g., in main.py) to configure the pool.
        You can override defaults by passing kwargs (host, user, password, database, pool_size, etc.).
        """
        if cls._pool is not None:
            return

        dbconfig = {
            "host": "localhost",
            "user": "root",
            "password": "",
            "database": "keny",
            # Hardened settings
            "connection_timeout": 20,      # fail fast if server is down
            "autocommit": False,
            "raise_on_warnings": False,    # don't raise 1050 warnings on CREATE IF NOT EXISTS
            "allow_local_infile": True,
            "use_pure": True,
            # Safe to include; ignored on older drivers
            
        }
        dbconfig.update(overrides or {})

        pool_kwargs = {
            "pool_name": dbconfig.pop("pool_name", "mypool"),
            "pool_size": int(dbconfig.pop("pool_size", 32)),
            "pool_reset_session": True,
        }

        cls._cfg = {**pool_kwargs, **dbconfig}
        cls._pool = mysql.connector.pooling.MySQLConnectionPool(
            **pool_kwargs,
            **dbconfig
        )

    @classmethod
    def get_connection(cls):
        """
        Borrow a connection from the pool.
        Ensures:
          - no unread results left on the socket (consume_results)
          - socket is alive (ping with reconnect)
        """
        if cls._pool is None:
            # Fallback init if the app didn't call init_pool() yet
            cls.init_pool()

        conn = cls._pool.get_connection()

        # Swallow any pending results on this socket (prevents "Unread result found")
        try:
            conn.consume_results()
        except Exception:
            pass

        # Ensure the socket is alive; reconnect transparently if needed
        try:
            conn.ping(reconnect=True, attempts=1, delay=0)
        except mysql.connector.Error:
            try:
                conn.close()
            except Exception:
                pass
            conn = cls._pool.get_connection()
            try:
                conn.consume_results()
            except Exception:
                pass
            conn.ping(reconnect=True, attempts=1, delay=0)
        cur = conn.cursor()
        try:
            cur.execute("USE keny;")
        finally:
            cur.close()
        return conn



class DatabaseConnection:
    """
    Convenience wrapper when you want a single connection + cursor.
    """
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.engine = None

    def create_engine(self):
        """Create a resilient SQLAlchemy engine (recommended for to_sql / ORM)."""
        try:
            import sqlalchemy
            self.engine = sqlalchemy.create_engine(
                "mysql+mysqlconnector://root:@localhost/keny",
                pool_pre_ping=True,       # validate before handing out
                pool_recycle=300,         # recycle often so server doesn't kill idle sockets
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                connect_args={
                    "connection_timeout": 20,
                    "allow_local_infile": True,
                    "use_pure": True,
                },
            )
        except Exception as e:
            print(f"Error creating engine: {e}")
            self.engine = None
    

    @staticmethod
    def table_exists(cur, table_name: str) -> bool:
        cur.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = %s LIMIT 1",
            (table_name,)
        )
        return cur.fetchone() is not None

    @staticmethod
    def ensure_currency_and_app_settings(conn):
        """
        Idempotent bootstrap: guarantees `currency` and `app_settings` exist
        with a valid FK. Safe to call on any page before first SELECT.
        """
        cur = conn.cursor()
        try:
            # Force DB context (guard in case the pool socket is on no schema)
            cur.execute("CREATE DATABASE IF NOT EXISTS keny;")
            cur.execute("USE keny;")

            # --- PARENT: currency ---
            cur.execute("""
                CREATE TABLE IF NOT EXISTS currency (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    code CHAR(3) NOT NULL UNIQUE,
                    name VARCHAR(64) NOT NULL UNIQUE
                ) ENGINE=InnoDB
                DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """)
            # normalize engine, defaults, and the column (repairs legacy installs)
            cur.execute("ALTER TABLE currency ENGINE=InnoDB")
            cur.execute("ALTER TABLE currency CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cur.execute("""
                ALTER TABLE currency
                MODIFY code CHAR(3)
                CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                NOT NULL
            """)
            # ensure UNIQUE on code
            try:
                cur.execute("ALTER TABLE currency ADD CONSTRAINT uq_currency_code UNIQUE (`code`)")
            except MySQLError:
                # already unique/indexed → ignore
                pass

            # seed
            cur.executemany(
                "INSERT IGNORE INTO currency (code, name) VALUES (%s, %s)",
                [
                    ("INR", "Indian Rupee"),
                    ("USD", "US Dollar"),
                    ("EUR", "Euro"),
                    ("GBP", "Pound Sterling"),
                    ("JPY", "Japanese Yen"),
                    ("AUD", "Australian Dollar"),
                    ("CAD", "Canadian Dollar"),
                    ("KES", "Kenyan Shilling"),
                ],
            )

            if not DatabaseConnection.table_exists(cur, "app_settings"):
                try:
                    cur.execute("""
                        CREATE TABLE app_settings (
                            id TINYINT PRIMARY KEY,
                            selected_currency_code CHAR(3) NOT NULL,
                            CONSTRAINT fk_app_currency
                              FOREIGN KEY (selected_currency_code)
                              REFERENCES currency(code)
                              ON UPDATE CASCADE
                              ON DELETE RESTRICT
                        ) ENGINE=InnoDB
                          DEFAULT CHARSET=utf8mb4
                          COLLATE=utf8mb4_unicode_ci
                    """)
                except MySQLError as e:
                    if e.errno == 1005:
                        cur.execute("ALTER TABLE currency ENGINE=InnoDB")
                        cur.execute("""
                            ALTER TABLE currency
                              MODIFY code CHAR(3)
                              CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                              NOT NULL
                        """)
                        cur.execute("""
                            CREATE TABLE app_settings (
                                id TINYINT PRIMARY KEY,
                                selected_currency_code CHAR(3) NOT NULL,
                                CONSTRAINT fk_app_currency
                                  FOREIGN KEY (selected_currency_code)
                                  REFERENCES currency(code)
                                  ON UPDATE CASCADE
                                  ON DELETE RESTRICT
                            ) ENGINE=InnoDB
                              DEFAULT CHARSET=utf8mb4
                              COLLATE=utf8mb4_unicode_ci
                        """)
                    else:
                        raise

            cur.execute("""
                INSERT IGNORE INTO app_settings (id, selected_currency_code)
                VALUES (1, 'INR')
            """)

            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

   

    def create_database(self):
        from sqlalchemy import create_engine, text
        engine = create_engine("mysql+mysqlconnector://root:@localhost:3306")

        # Open a connection
        with engine.connect() as conn:
            conn.execute(text("CREATE DATABASE IF NOT EXISTS keny;"))
            print("Database created successfully!")


    def connect(self):
        """Get a pooled mysql-connector connection (not SQLAlchemy)."""
        try:
            self.conn = DatabaseConnectionPool.get_connection()
            # Use plain cursor by default; use buffered=True for SELECTs where needed
            self.cursor = self.conn.cursor()
        except mysql.connector.Error as err:
            print(f"Error: {err}")
            self.conn = None
            self.cursor = None

    def close(self):
        try:
            if self.cursor:
                self.cursor.close()
        except Exception:
            pass
        try:
            if self.conn:
                self.conn.close()
        except Exception:
            pass
        self.cursor = None
        self.conn = None

    def _safe_create_index(self, cursor, table, index_name, columns_sql):
        """Create index; ignore if it already exists (works across MySQL/MariaDB)."""
        try:
            cursor.execute(f"CREATE INDEX {index_name} ON {table} ({columns_sql})")
        except mysql.connector.Error as e:
            if e.errno in (errorcode.ER_DUP_KEYNAME, 1061):  # 1061 = duplicate key name
                pass
            else:
                try:
                    cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({columns_sql})")
                except Exception:
                    pass

    def create_tables(self):
        self.connect()
        if not self.conn:
            raise Exception("Database connection failed")
        cursor = self.conn.cursor()
        try:
            self.conn.start_transaction()

            cursor.execute("CREATE DATABASE IF NOT EXISTS keny;")
            cursor.execute("USE keny;")
            self.conn.commit()

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {DISBURSMENT} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    loan_id VARCHAR(255) UNIQUE,
                    branch VARCHAR(255),
                    disbursement_id VARCHAR(255) UNIQUE,
                    amount_disbursed DECIMAL(10, 2),
                    transcode VARCHAR(255),
                    disb_date DATE,
                    borrower_name VARCHAR(255),
                    principal DECIMAL(10, 2),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)
            self._safe_create_index(cursor, DISBURSMENT, "idx_loan_id", "`loan_id`")
            self._safe_create_index(cursor, DISBURSMENT, "idx_disb_date", "`disb_date`")

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {RECEIPT} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    receipt_date DATE,
                    loan_id VARCHAR(255),
                    receipt_id VARCHAR(255),
                    amount_received DECIMAL(10, 2),
                    transcode VARCHAR(50),
                    resolve VARCHAR(50) DEFAULT 'U',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)
            self._safe_create_index(cursor, RECEIPT, "idx_receipt_loan_id", "`loan_id`")
            self._safe_create_index(cursor, RECEIPT, "idx_receipt_date", "`receipt_date`")

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {MEMBER} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    disb_date DATE,
                    borrower_name VARCHAR(255),
                    branch VARCHAR(255),
                    membership_income DECIMAL(10, 2),
                    transcode VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {BRANCH} (
                    branch VARCHAR(255) PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {FILE_HASES} (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    file_name VARCHAR(255),
                    file_hash VARCHAR(255) UNIQUE,
                    last_upload TIMESTAMP NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {LAST_upload} (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    file_type VARCHAR(20) NOT NULL,
                    timestamp TIMESTAMP,
                    file_hash VARCHAR(64)
                ) ENGINE=InnoDB
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {UPLOAD_SUMMARY} (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    file_name VARCHAR(255) NOT NULL,
                    record_count INT NOT NULL,
                    valid_rows INT DEFAULT 0,
                    error_rows INT DEFAULT 0,
                    total_amount DECIMAL(18,2) NULL,
                    min_date DATE NULL,
                    max_date DATE NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    file_type VARCHAR(50) NOT NULL
                ) ENGINE=InnoDB
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS receipt_unresolved (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    receipt_date DATE,
                    loan_id VARCHAR(255),
                    receipt_id VARCHAR(255),
                    amount_received DECIMAL(10,2),
                    transcode VARCHAR(50),
                    resolve VARCHAR(50) DEFAULT 'U',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS file_status (
                    file_type      ENUM('Disbursement','Receipt','Members','Branch') PRIMARY KEY,
                    last_upload    DATETIME,
                    min_date       DATE,
                    max_date       DATE,
                    record_count   INT,
                    total_amount   DECIMAL(18,2),
                    last_filename  VARCHAR(255),
                    last_hash      CHAR(64)
                ) ENGINE=InnoDB;
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS file_ingests (
                    id            BIGINT AUTO_INCREMENT PRIMARY KEY,
                    file_type     ENUM('Disbursement','Receipt','Members','Branch') NOT NULL,
                    filename      VARCHAR(255) NOT NULL,
                    content_hash  CHAR(64) NOT NULL,
                    rows_ok       INT NOT NULL,
                    rows_err      INT NOT NULL,
                    uploaded_at   DATETIME NOT NULL,
                    UNIQUE KEY uk_hash (file_type, content_hash)
                ) ENGINE=InnoDB;
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS company_info (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    company_name VARCHAR(255) NOT NULL,
                    logo_url VARCHAR(500),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB
            """)
            DatabaseConnection.ensure_currency_and_app_settings(self.conn)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()
            self.close()
