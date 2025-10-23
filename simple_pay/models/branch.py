from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class BranchModel(BaseModel):  
    branch : str  # Branch name
    created_at: Optional[str] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")