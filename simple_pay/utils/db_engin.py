# utils/db_engine.py
from sqlalchemy import create_engine

DB_USER = "root"
DB_PWD = ""
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
