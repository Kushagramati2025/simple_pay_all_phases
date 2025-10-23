import os
import tempfile
import time
# from simple_pay.utils.database_connection  import DatabaseConnection
import streamlit as st
from simple_pay.utils.database_connection import DatabaseConnection

# --- RUN MIGRATIONS FROM DATABASECONNECTION ---
def run_migrations():
    try:
        db = DatabaseConnection()  # Automatically creates tables
        db.create_database()
        db.create_engine()
        db.create_tables()
        st.success("Database connected and tables created.")
    except Exception as e:
        st.error(f"Migration failed: {str(e)}")

run_migrations()

from simple_pay.utils.database_connection import DatabaseConnectionPool


# Initialize the pool ONCE at startup
DatabaseConnectionPool.init_pool()
os.makedirs(r"C:\project_v2\simple-pay-v2\simple_pay\editor",exist_ok=True)
# Disable file watching for performance
os.environ["STREAMLIT_SERVER_ENABLE_STATIC_WEB_ROOT"] = "false"
os.environ["STREAMLIT_SERVER_FILE_WATCHER_TYPE"] = "none"
os.environ["STREAMLIT_SERVER_WATCH_FILE_BLACKLIST"] = (
    r".*[\\/]__pycache__[\\/].*|"          
    r".*\.pyc.*|"                           
    r".*\.tmp$|"                            
    f"{tempfile.gettempdir()}.*"
)



# --- STREAMLIT CONFIG ---
st.set_page_config(layout="wide", page_title="Login Page", page_icon=":key:")
st.set_option('client.showSidebarNavigation', False)
with st.sidebar:
    if st.button("📊 Data_Upload"):
        user_id = st.session_state.get("user_id")
        st.session_state["user_id"] = user_id
        st.switch_page("pages/Data_Upload.py")
    if st.button("📈 Reports") :
        user_id = st.session_state.get("user_id")
        st.session_state["user_id"] = user_id
        st.switch_page("pages/Reports.py")
    if st.button("🚪 Logout"):
        st.session_state.clear()
        st.switch_page("pages/Login.py")
# --- LOGIN ROUTING LOGIC ---
if 'authenticated' not in st.session_state:
    
    st.session_state.authenticated = False
    st.session_state.role = None


if not st.session_state.authenticated:
    # if session_state["user_id"] is None:
    #     with open(r"C:\project_v2\simple-pay-v2\simple_pay\editor\v1.txt", "w") as f:
    #                 f.write("")
    st.session_state.logged_in = True
    st.switch_page("pages/Login.py")
    if st.session_state.role == "admin":
        user_id = st.session_state.get("user_id")
        st.session_state["user_id"] = user_id
        st.switch_page("pages/Data_Upload.py")
    else:
        user_id = st.session_state.get("user_id")
        st.session_state["user_id"] = user_id
        st.switch_page("pages/Reports.py")
    # if st.session_state.role == "admin":
    #     st.switch_page("pages/Data_Upload.py")
    # else:
    #     st.switch_page("pages/Reports.py")

