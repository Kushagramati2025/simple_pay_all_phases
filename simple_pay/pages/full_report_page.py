# pages/Loan Detail Report.py
import streamlit as st
from reports_dashboards.full_report import loan_detail_report  # import your function
st.set_page_config(layout="wide")
loan_detail_report(session_prefix="loan_detail")
