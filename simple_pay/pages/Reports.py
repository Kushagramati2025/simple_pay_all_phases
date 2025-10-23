import streamlit as st
import pandas as pd
from simple_pay.utils.database_connection import DatabaseConnection
from reports_dashboards.full_report import loan_detail_report
# from reports_dashboards.Interest_Received import Interest_Received
# from reports_dashboards.Principal_Received import Principal_Received   
# from reports_dashboards.Penalty_Received import Penalty_Received
# from reports_dashboards.Membership import Members   
# from reports_dashboards.payment_received import PaymentReceived
from reports_dashboards.Disbursement import *
# from reports_dashboards.Total import Total


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
        st.divider()
    st.divider()
    if st.sidebar.button("Full Report"):
        st.switch_page("pages/full_report_page.py")
    if st.sidebar.button("Collection Report"):
        st.switch_page("pages/collection_report.py")
    if st.sidebar.button("Branch"):
        st.switch_page("pages/region.py")
    if st.sidebar.button("Defulater"):
        st.switch_page("pages/defulters.py")

    
# -----------------------------------
# Page Config
st.set_page_config(page_title="Reports Dashboard", layout="wide")

# -----------------------------------
# Custom CSS
st.markdown("""
<style>
/* Remove padding and set height */
.block-container {
    padding: 0rem 2rem 2rem 2rem;
    max-width: 100%;
}

/* Prevent full-page scroll */
html, body, [data-testid="stAppViewContainer"], [data-testid="stAppViewBlockContainer"] {
    height: 100vh !important;
    overflow: hidden !important;
}

/* Make main content scrollable inside */
section.main > div {
    height: calc(100vh - 100px);
    overflow-y: auto;
    padding: 1.5rem;
    background-color: #ffffff;
    border-radius: 10px;
    box-shadow: 0px 4px 16px rgba(0,0,0,0.05);
}

/* Title styling */
h1 {
    font-size: 38px;
    color: #1e3d59;
    font-weight: bold;
    border-left: 6px solid #007acc;
    padding-left: 15px;
}

/* Tab styles */
.stTabs [role="tablist"] {
    border-bottom: 2px solid #ccc;
    margin-bottom: 1rem;
    margin-top:35px;
}

.stTabs [role="tab"] {
    min-width: 150px;
    font-size: 15px;
    font-weight: 600;
    padding: 10px 20px;
    border-radius: 10px 10px 0 0;
    border: 1px solid transparent;
    color: #2c3e50;
}

.stTabs [role="tab"]:hover {
    background-color: #e8f0fe;
    border: 1px solid #cfd8dc;
}

.stTabs [aria-selected="true"] {
    background-color: #ffffff;
    border: 2px solid #007acc;
    border-bottom: none;
    color: #007acc;
}

/* Hide footer */
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# -----------------------------------
# def generate_charts():
#     try:
#         db = DatabaseConnection()
#         db.connect()
#         conn = db.conn

       

#         tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
#             "Disbursement",
#             "Interest Received",
#             "Principal Received",
#             "Penalty Received",
#             "Membership",
#             "Payment Received",
#             "Total"
#             "Summary"
#         ])

#         with tab1:
#             # st.markdown("###  Disbursement")
#             Disbursement()

#         with tab2:
#             # st.markdown("###  Interest Received")
#             Interest_Received()

#         with tab3:
#             # st.markdown("#  Principal Received")
#             Principal_Received()

#         with tab4:
#             # st.markdown("#  Penalty Received")
#             Penalty_Received()

#         with tab5:
#             # st.markdown("#  Membership Income")
#             Members()

#         with tab6:
#             # st.markdown("#  Payment Received")
#             PaymentReceived()
            
        
#         with tab7:
#             # st.markdown("# Payment Received")
#             Total()
            
#         # with tab8:
#         #     get_upload_summary_report()
            

#     except Exception as e:
#         st.error(f"Error initializing dashboard: {str(e)}")
#     finally:
#         if 'db' in locals():
#             db.close()
#--------------------------------------------------------------------------------------------------------------------
#-----------------------------------------
def generate_charts():
    try:
        db = DatabaseConnection()
        db.connect()
        conn = db.conn

        # st.markdown("## 📊 Financial Reports Dashboard")

        # tab1= st.tab([
        #     "Disbursement",
        #     # "Graphs"
        #     # "Interest Received"
        #     # "Principal Received",
        #     # "Penalty Received",
        #     # "Membership",
        #     # "Payment Received",
        #     # "Total"
        #     # "Summary"
        # ])
        # filtered_df = None
        # with tab1:
            # st.markdown("###  Disbursement")
        try:
            filtered_df,total_principal,total_principal_paid,principal_paid_pct,remaining_pct,total_interest,total_interest_paid,interest_paid_pct,interest_remaining_pct,grand_total,grand_total_paid,grand_total_paid_pct,grand_total_remaining_pct = Disbursement()
        except Exception as e:
            import traceback
            traceback.print_exc()

        # with tab2:
        #     # st.markdown("###  Interest Received")
        #     if filtered_df is not None and not filtered_df.empty:
        #         try:
        #             graph1(filtered_df,total_principal,total_principal_paid,principal_paid_pct,remaining_pct,total_interest,total_interest_paid,interest_paid_pct,interest_remaining_pct,grand_total,grand_total_paid,grand_total_paid_pct,grand_total_remaining_pct)
        #         except Exception as e:
        #             import traceback
        #             traceback.print_exc()
        #     else:
        #         st.warning("No data to plot.")

        # with tab3:
        #     # st.markdown("#  Principal Received")
        #     Principal_Received()

        # with tab4:
        #     # st.markdown("#  Penalty Received")
        #     Penalty_Received()

        # with tab5:
        #     # st.markdown("#  Membership Income")
        #     Members()

        # with tab6:
        #     # st.markdown("#  Payment Received")
        #     PaymentReceived()
            
        
        # with tab7:
        #     # st.markdown("# Payment Received")
        #     Total()
            
        # with tab8:
        #     get_upload_summary_report()
            

    except Exception as e:
        st.error(f"Error initializing dashboard: {str(e)}")
    finally:
        if 'db' in locals():
            db.close()


#-----------------------------------------
# -----------------------------------
# if __name__ == "__main__":
# if 'authenticated' not in st.session_state or not st.session_state.authenticated:
#     st.error(" You must be logged in to view this page.")
# else:
#     # Top-right logout button
#     logout_col = st.columns([10, 8])[1]
#     with logout_col:
#         if st.button("Logout", key="logout_btn"):
#             st.session_state.authenticated = False
#             st.success("✅ Logged out successfully.")
#             st.rerun()

# def logout():
#     # Clear session state (this is like logging out)
#     for key in st.session_state.keys():
#         del st.session_state[key]
    
#     # Simulate redirection (can also use query params or session state)
#     st.success("Logged out successfully! Redirecting to login page...")
#     # time.sleep(1)  # Short delay
#     # st.experimental_set_query_params(page="login")  # Simulate redirect
#     st.switch_page("pages/1_Login.py")

# # Example use
# if st.button("Logout"):
#     logout()

# Simulated page routing (like checking what page to show)
# query_params = st.experimental_get_query_params()
# page = query_params.get("page", ["home"])[0]

# if page == "login":
#     st.write("### 🛂 Login Page")
#     # Add your login form here
# else:
#     st.write("### 🏠 Home Page")
    
    # Generate charts
generate_charts()
