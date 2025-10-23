from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class RecieptModel(BaseModel):
    loan_id: str
    receipt_date: str
    receipt_id: str
    amount_received: float
    transcode: str
    resolve: Optional[str] = "U"
    created_at: Optional[str] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
