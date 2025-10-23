
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
class DisbursementModel(BaseModel):
    
        loan_id: str  #             | LN001
        disb_date: str  #           | 2025-01-07
        borrower_name: str
        branch: str 
        disbursement_id: str
        amount_disbursed: float = 0.0
        transcode: str
        created_at: Optional[str] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # updated_at
        
        
    
    