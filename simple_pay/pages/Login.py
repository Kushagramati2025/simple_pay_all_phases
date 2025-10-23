import streamlit as st
import time
from simple_pay.utils.auth import init_db_wrapper, authenticate


# Initialize session state variables if they don't exist
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'role' not in st.session_state:
    st.session_state.role = None
if 'login_attempts' not in st.session_state:
    st.session_state.login_attempts = 0

def main():
    # Initialize database
    if not init_db_wrapper():
        st.error("Database initialization failed. Contact administrator.")
        st.stop()
    
    st.title("Login")
    
    with st.form("login_form"):
        
        username = st.text_input("Username", key="username_input")
        password = st.text_input("Password", type="password", key="password_input")
        submit = st.form_submit_button("Login")
        
        if submit:
            if not username or not password:
                st.error("Username and password are required")
            else:
                # Authenticate returns tuple (success, role, message)
                success, role, message, id = authenticate(username, password)
                
                if success:
                    st.session_state.authenticated = True
                    st.session_state.role = role
                    st.session_state.login_attempts = 0  # Reset attempts on success
                    st.success(message + " Redirecting...")
                    
                    # Add small delay for message to show before redirect
                    time.sleep(1)
                    
                    # Redirect based on role
                    if role == "admin":
                        def get_current_user():
                            return st.session_state.get("user_id", str(time.time()))

                        user_id = get_current_user()
                        st.session_state["user_id"] = user_id
                        st.session_state["u_id"] = id
                        st.switch_page("pages/Data_Upload.py")
                    else:
                        # st.session_state["user_id"] = user_id
                        st.switch_page("pages/Reports.py")
                else:
                    st.session_state.login_attempts += 1
                    remaining_attempts = 5 - st.session_state.login_attempts
                    
                    if remaining_attempts > 0:
                        st.error(f"{message}. {remaining_attempts} attempts remaining.")
                    else:
                        st.error(f"{message}. No attempts remaining. Please try again later.")
                        # Reset counter after 3 attempts
                        st.session_state.login_attempts = 0


# Only show the login form if not authenticated
if not st.session_state.authenticated:
    main()
else:
    # If already authenticated, redirect immediately
    if st.session_state.role == "admin":
        user_id = st.session_state.get("user_id")
        st.session_state["user_id"] = user_id
        st.switch_page("pages/Data_Upload.py")
    else:
        st.switch_page("pages/Reports.py")