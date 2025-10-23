import streamlit as st
import pandas as pd
from simple_pay.utils.database_connection import DatabaseConnection

def Members():
    try:
        #  Dashboard-style custom CSS
        st.markdown("""
            <style>
                /* General layout and background */
                .main {
                    background-color: #f4f7fa;
                }

                /* Title styling */
                .report-title {
                    font-size: 32px;
                    font-weight: 800;
                    color: #2c3e50;
                    margin-bottom: 1.5rem;
                    text-align: left;
                    border-left: 6px solid #3498db;
                    padding-left: 15px;
                }

                /* Date range message */
                .range-message {
                    font-size: 17px;
                    color: #555;
                    margin-bottom: 1.5rem;
                }

                /* Total amount summary */
                .total-box {
                    font-size: 20px;
                    font-weight: bold;
                    color: #1e8449;
                    background-color: #d4efdf;
                    padding: 15px 20px;
                    border-radius: 10px;
                    width: fit-content;
                    box-shadow: 0px 4px 10px rgba(0,0,0,0.1);
                    margin-top: 1.5rem;
                    margin-bottom: 2rem;
                    transition: transform 0.2s;
                }

                .total-box:hover {
                    transform: scale(1.02);
                }

                /* Dataframe container */
                .stDataFrame {
                    border-radius: 12px !important;
                    border: 1px solid #d0d0d0 !important;
                    margin-bottom: 2rem;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                }

                /* Label for date input */
                label[for="Members_Date_input"] {
                    font-size: 16px;
                    font-weight: 600;
                    color: #2c3e50;
                }
            </style>
        """, unsafe_allow_html=True)

        # 🔌 Database connection
        db = DatabaseConnection()
        db.connect()
        conn = db.conn

        #  Query members table
        query = "SELECT disb_date, borrower_name, branch, membership_income, transcode FROM keny.members"
        df = pd.read_sql(query, conn)

        if df.empty:
            st.warning("No members data available.")
            return

        # Preprocess and clean
        df['disb_date'] = pd.to_datetime(df['disb_date'])
        df.rename(columns={
            "disb_date": "Date",
            "borrower_name": "Name",
            "branch": "Branch",
            "membership_income": "Amount",
            "transcode": "Transaction Code"
        }, inplace=True)

        #  Title
        
        #  Date range filter
        min_date = df['Date'].min().date()
        max_date = df['Date'].max().date()

        start_date, end_date = st.date_input(
            "Select date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="Members_Date_input"
        )

        # 🔍 Filter based on date
        filtered_df = df[
            (df['Date'] >= pd.to_datetime(start_date)) & 
            (df['Date'] <= pd.to_datetime(end_date))
        ]

        #  Info
        st.markdown(
            f'<div class="range-message"> Showing records from <b>{start_date}</b> to <b>{end_date}</b></div>',
            unsafe_allow_html=True
        )
        filtered_df.index = filtered_df.index + 1 
        #  Table display
        st.dataframe(
            filtered_df,
            use_container_width=True,
            height=200,  # Approximate height to fit 5 rows; adjust if needed
        )
        
        

        #  Total amount summary
        total_amount = filtered_df["Amount"].sum()
        st.markdown(
            f'<div class="total-box">Total Membership Amount: KES {total_amount:,.2f}</div>',
            unsafe_allow_html=True
        )

    except Exception as e:
        st.error(f"Error fetching Members data: {str(e)}")

    finally:
        if 'db' in locals():
            db.close()
