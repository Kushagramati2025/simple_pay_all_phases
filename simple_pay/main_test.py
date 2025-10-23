import pandas as pd
from simple_pay.service.disbursement_service import DisbursementService
from simple_pay.service.reciept_service import Reciept_service

import  time

from simple_pay.utils.database_connection import DatabaseConnectionPool


# Initialize the pool ONCE at startup
DatabaseConnectionPool.init_pool()

def read_disb_data():
    data =  {
        "Disb. Date": ["01-07-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Borrower Name": ["John Doe"],
        "Branch": ["Mumbai"],
        "Disbursement ID": ["DISB001"],
        "Amount Disbursed": [10000],
        "Transcode": ["CASH"]
    }
    return "disbursement", pd.DataFrame(data)
    
    # data =  {
    #     "Disb. Date": ["07-01-2025", "07-01-2025","07-01-2025", "07-01-2025", "07-01-2025", "07-01-2025"],
    #     "SUPERLENDER LOAN ID": ["LN001", "LN002","LN003","LN004","LN005","LN006"],
    #     "Borrower Name": ["John Doe", "Jane Smith","Sam Cut", "Ben Bucket", "Joe Root","Harry Brook"],
    #     "Branch": ["Mumbai", "Pune","Mumbai", "Pune","Mumbai", "Pune"],
    #     "Disbursement ID": ["DISB001", "DISB002","DISB003","DISB004","DISB005","DISB006"],
    #     "Amount Disbursed": [10000, 10000,10000,10000,10000,10000],
    #     "Transcode": ["CASH", "BANK","CASH", "BANK","CASH", "BANK"]
    # }
    # return "disbursement", pd.DataFrame(data)

def read_reciept_data():
    data = {
        "Receipt Date": ["05-07-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [5000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)


def read_recipt_test_case2():
    data = {
        "Receipt Date": ["25-07-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [1000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)

# 35
def read_recipt_test_case3():
    data = {
        "Receipt Date": ["07-08-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [1000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)

# 45
def read_recipt_test_case4():
    data = {
        "Receipt Date": ["15-08-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [1000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)

# 45
def read_recipt_test_case5():
    data = {
        "Receipt Date": ["20-08-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [1000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)

# 60
def read_recipt_test_case6():
    data = {
        "Receipt Date": ["01-09-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [1000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)

# 90
def read_recipt_test_case7():
    data = {
        "Receipt Date": ["15-10-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [1000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)

def read_recipt_test_case8():
    data = {
        "Receipt Date": ["15-10-2025"],
        "SUPERLENDER LOAN ID": ["LN001"],
        "Receipt ID": ["REC001"],
        "Amount Received": [1000],
        "Transcode": ["CASH"],
        "Resolve": [False]
    }
    return "receipt", pd.DataFrame(data)

    # The `data` dictionary in the `read_reciept_data` function is creating a dataset containing
    # information about receipts. Each key in the dictionary represents a column in the dataset, and
    # the corresponding list contains the values for that column.
    # data = {
    #     "Receipt Date": ["07-05-2025", "07-23-2025","08-07-2025", "08-27-2025", "09-09-2025", "08-10-2025"],
    #     "SUPERLENDER LOAN ID": ["LN001", "LN002","LN001", "LN004", "LN005", "LN006"],
    #     "Receipt ID": ["REC001", "REC002","REC003", "REC004","REC005", "REC006"],
    #     "Amount Received": [5000,5000,5000,5000,8000,5000],
    #     "Transcode": ["CASH", "BANK","CASH", "BANK","CASH", "BANK"],
    #     "Resolve": [False, True,False, True,False, True]
    # }
    # return "receipt", pd.DataFrame(data)

if __name__ == "__main__":
    filetype, df = read_disb_data()
    DisbursementService = DisbursementService(df)
    print(Disbursementsimple_pay.service.disbursement_insert_process())
    
    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()
    
    time.sleep(2)  # Wait for the disbursement to be processed
    filetype, df = read_reciept_data()
    reciept_service = Reciept_service(df)
    print(reciept_simple_pay.service.reciept_insert_process())

    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()
    
    # test case 2
    print("✅ Data uploaded to disbursement and receipt tables.")
    time.sleep(2)  # Wait for the disbursement to be processed
    filetype, df = read_recipt_test_case2()
    reciept_service = Reciept_service(df)
    print(reciept_simple_pay.service.reciept_insert_process())
    
    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()
    
    # test case 3
    print("✅ Data uploaded to disbursement and receipt tables.")
    time.sleep(2)  # Wait for the disbursement to be processed
    filetype, df = read_recipt_test_case3()
    reciept_service = Reciept_service(df)
    print(reciept_simple_pay.service.reciept_insert_process())

    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()
    
    print("✅ Data uploaded to disbursement and receipt tables.")
    time.sleep(2)  # Wait for the disbursement to be processed
    filetype, df = read_recipt_test_case4()
    reciept_service = Reciept_service(df)
    print(reciept_simple_pay.service.reciept_insert_process())
    
    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()
    
    print("✅ Data uploaded to disbursement and receipt tables.")
    time.sleep(2)  # Wait for the disbursement to be processed
    filetype, df = read_recipt_test_case5()
    reciept_service = Reciept_service(df)
    print(reciept_simple_pay.service.reciept_insert_process())
    
    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()
    
    print("✅ Data uploaded to disbursement and receipt tables.")
    time.sleep(2)  # Wait for the disbursement to be processed
    filetype, df = read_recipt_test_case6()
    reciept_service = Reciept_service(df)
    print(reciept_simple_pay.service.reciept_insert_process())
    
    # Track received values
    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()
    
    print("✅ Data uploaded to disbursement and receipt tables.")
    time.sleep(2)  # Wait for the disbursement to be processed
    filetype, df = read_recipt_test_case7()
    reciept_service = Reciept_service(df)
    print(reciept_simple_pay.service.reciept_insert_process())
    
    # Track received values
    #tracker = ReceivedComponentTracker()
   # tracker.update_all_components()

    print("✅ principal_received, interest_received, penalty_received tables updated.")
