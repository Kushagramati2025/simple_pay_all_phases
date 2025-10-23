import streamlit as st
from datetime import datetime
from .db_utils import get_db_connection
import logging
from simple_pay.utils.database_connection import DatabaseConnection

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db_wrapper():
    """
    Initialize database tables if they don't exist
    Creates users and last_upload tables with proper schema
    """
    conn = DatabaseConnection()
    conn.connect()
    # conn.cursor
    try:
        
        
        # Create users table if not exists
        conn.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password VARCHAR(100) NOT NULL,
                role VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create last_upload table with all required columns
        conn.cursor.execute("""
            CREATE TABLE IF NOT EXISTS last_upload (
                id SERIAL PRIMARY KEY,
                file_type VARCHAR(20) NOT NULL,
                timestamp TIMESTAMP,
                file_hash VARCHAR(64)
            )
        """)
        
        # Ensure all columns exist (for existing tables)
        # conn.cursor.execute("""
        #     DO $$
        #     BEGIN
        #         -- Add file_hash if missing
        #         IF NOT EXISTS (
        #             SELECT 1 FROM information_schema.columns 
        #             WHERE table_name='last_upload' AND column_name='file_hash'
        #         ) THEN
        #             ALTER TABLE last_upload ADD COLUMN file_hash VARCHAR(64);
        #         END IF;
                
        #         -- Add timestamp if missing
        #         IF NOT EXISTS (
        #             SELECT 1 FROM information_schema.columns 
        #             WHERE table_name='last_upload' AND column_name='timestamp'
        #         ) THEN
        #             ALTER TABLE last_upload ADD COLUMN timestamp TIMESTAMP;
        #         END IF;
        #     END $$;
        # """)
        
        # Create default admin user if not exists (insecure - should be changed after first login)
        conn.cursor.execute("SELECT username FROM users WHERE username = 'admin'")
        if not conn.cursor.fetchone():
            conn.cursor.execute(
                "INSERT INTO users (username, password, role) VALUES (%s, %s, %s)",
                ('admin', 'admin123', 'admin')  # Note: In production, use hashed passwords
            )
            logger.info("Default admin user created")
        
        # Initialize last_upload records if not exists
        for file_type in ["Disbursement", "Receipt", "Members", "Branch"]:
            conn.cursor.execute(
                "SELECT file_type FROM last_upload WHERE file_type = %s LIMIT 1",
                (file_type,)
            )
            if not conn.cursor.fetchone():
                conn.cursor.execute(
                    "INSERT INTO last_upload (file_type, timestamp) VALUES (%s, NULL)",
                    (file_type,)
                )
                logger.info(f"Initialized last_upload record for {file_type}")
        
        conn.conn.commit()
        logger.info("Database initialization completed successfully")
        return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = f"Database initialization error: {str(e)}"
        logger.error(error_msg)
        st.error(error_msg)
        return False
    finally:
        if 'conn' in locals():
            conn.close()

def authenticate(username, password):
    """
    Authenticate user credentials
    
    Args:
        username (str): Username
        password (str): Plain text password
    
    Returns:
        tuple: (success: bool, role: str, message: str)
    """
    databaseConnection = DatabaseConnection()
    databaseConnection.create_tables()
    databaseConnection.connect()
    # conn.cursor
    try:
        # conn = get_db_connection()
        cursor = databaseConnection.cursor
        
        cursor.execute(
            "SELECT password, role, id FROM users WHERE username = %s", 
            (username,)
        )
        result = cursor.fetchone()
        
        if result:
            stored_password = result[0]
            role = result[1]
            id = result[2]
            # Plain text comparison (insecure - consider using hashed passwords)
            if stored_password == password:
                logger.info(f"Successful login for user: {username}")
                return True, role, "Login successful",id
            logger.warning(f"Failed login attempt for user: {username} (incorrect password)")
            return False, None, "Incorrect password"
        logger.warning(f"Failed login attempt: username not found - {username}")
        return False, None, "Username not found",0
    except Exception as e:
        error_msg = f"Authentication error: {str(e)}"
        logger.error(error_msg)
        return False, None, error_msg,0
    finally:
        
        if 'conn' in locals():
            databaseConnection.close()

def create_user(username, password, role):
    """
    Create a new user in the database
    
    Args:
        username (str): Unique username
        password (str): Plain text password
        role (str): 'employee' or 'admin'
    
    Returns:
        tuple: (success: bool, message: str)
    """
    if not username or not password:
        return False, "Username and password are required"
    if len(username) < 4:
        return False, "Username must be at least 4 characters"
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if role not in ['employee', 'admin']:
        return False, "Invalid role specified"

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if username exists
        cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
        if cursor.fetchone():
            return False, "Username already exists"
        
        # Insert new user (with plain text password - consider hashing in production)
        cursor.execute(
            "INSERT INTO users (username, password, role, created_at) VALUES (%s, %s, %s, %s)",
            (username, password, role, datetime.now())
        )
        conn.commit()
        logger.info(f"New user created: {username} ({role})")
        return True, f"User {username} created successfully"
    except Exception as e:
        error_msg = f"User creation error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
    finally:
        if 'conn' in locals():
            conn.close()

def delete_user(username):
    """
    Delete a user from the database
    
    Args:
        username (str): Username to delete
    
    Returns:
        tuple: (success: bool, message: str)
    """
    if username == 'admin':
        return False, "Cannot delete default admin user"
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if user exists
        cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
        if not cursor.fetchone():
            return False, f"User {username} does not exist"
        
        # Delete user
        cursor.execute("DELETE FROM users WHERE username = %s", (username,))
        conn.commit()
        logger.info(f"User deleted: {username}")
        return True, f"User {username} deleted successfully"
    except Exception as e:
        error_msg = f"User deletion error: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
    finally:
        if 'conn' in locals():
            conn.close()