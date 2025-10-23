from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class UploadSummaryModel(BaseModel):  
    file_name: str
    record_count: int
    valid_rows: int
    error_rows: int
    total_amount: Optional[float] = None
    min_date: Optional[str] = None
    max_date: Optional[str] = None
    created_at: str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")