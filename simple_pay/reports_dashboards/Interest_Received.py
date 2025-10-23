import streamlit as st
import pandas as pd
from simple_pay.utils.database_connection import DatabaseConnection

def Interest_Received():
    #  Unified modern dashboard styling
    st.markdown("""
        <style>
            .main {
                background-color: #f4f7fa;
            }

            .header {
                font-size: 32px;
                font-weight: 800;
                color: #2c3e50;
                margin-bottom: 1.5rem;
                border-left: 6px solid #3498db;
                padding-left: 15px;
            }

            .range-message {
                font-size: 17px;
                color: #555;
                margin-bottom: 1.5rem;
            }

            .stDataFrame {
                border-radius: 12px !important;
                border: 1px solid #d0d0d0 !important;
                margin-bottom: 2rem;
                box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            }

            label[for="Interest_Date_input"] {
                font-size: 16px;
                font-weight: 600;
                color: #2c3e50;
            }

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
        </style>
    """, unsafe_allow_html=True)

    #  Title
    
    try:
        # 🔌 Connect to database
        db = DatabaseConnection()
        db.connect()
        conn = db.conn

        #  Query data
        query = "SELECT receipt_date, loan_id, interest_received FROM keny.interest_received"
        df = pd.read_sql(query, conn)

        if df.empty:
            st.warning("No interest data available.")
            return

        #  Clean data
        df['receipt_date'] = pd.to_datetime(df['receipt_date'])
        df.rename(columns={
            "receipt_date": "Date",
            "loan_id": "Loan ID",
            "interest_received": "Interest"
        }, inplace=True)

        min_date = df['Date'].min().date()
        max_date = df['Date'].max().date()

        #  Date filter
        start_date, end_date = st.date_input(
            "Select date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            key="Interest_Date_input"
        )

        # 🔍 Filter by date
        filtered_df = df[
            (df['Date'] >= pd.to_datetime(start_date)) &
            (df['Date'] <= pd.to_datetime(end_date))
        ]
        filtered_df.index = filtered_df.index + 1 
        #  Date summary
        st.markdown(
            f'<div class="range-message"> Showing records from <b>{start_date}</b> to <b>{end_date}</b></div>',
            unsafe_allow_html=True
        )

        #  Table
        
        st.dataframe(
            filtered_df,
            use_container_width=True,
            height=200,  # Approximate height to fit 5 rows; adjust if needed
        )
          
            
        #  Summary metrics
        total_interest = filtered_df['Interest'].sum()
        total_records = len(filtered_df)

        
        st.markdown(
            f'<div class="total-box">Total Interest Received: KES {total_interest:,.2f}</div>',
            unsafe_allow_html=True
        )

        

    except Exception as e:
        st.error(f" Error fetching interest data: {str(e)}")

    finally:
        if 'db' in locals():
            db.close()
