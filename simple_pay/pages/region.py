import streamlit as st
from reports_dashboards.region_wise import branch_report  # import your function
st.set_page_config(layout="wide")
branch_report()

