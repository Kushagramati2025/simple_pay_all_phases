# utils/db_simple_pay.utils.py
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables

def get_db_connection():
    """Create and return PostgreSQL connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "simple_pay"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "1234")
    )