#defaulter_report()

import streamlit as st
from reports_dashboards.defaulter import defaulter_report  
st.set_page_config(layout="wide")
defaulter_report()

