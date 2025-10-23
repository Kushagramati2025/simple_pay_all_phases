from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class MemebersModel(BaseModel):
    Disb_Date: str  # Disbursement date 
    Borrower_Name: str # Name of the borrower 
    Branch: str # Branch name  
    Membership_Income: float  # Membership income
    Transcode : str  # Transaction code
    created_at: Optional[str] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
