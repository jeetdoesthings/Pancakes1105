from pydantic import BaseModel, Field, constr, validator
from typing import Optional
from datetime import date
import uuid

class UniversalRFP(BaseModel):
    rfpId: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique ID for the RFP")
    title: str = Field(..., max_length=200, description="RFP title or short description")
    productName: str = Field(..., max_length=100, description="Requested product or service (normalized name)")
    category: Optional[str] = Field(None, max_length=100, description="Standardized product category")
    quantity: int = Field(..., gt=0, description="Number of units requested")
    unit: str = Field(..., max_length=20, description="Measurement unit (e.g. 'each', 'kg', 'service')")
    deadline: date = Field(..., description="Proposal submission deadline")
    budget: Optional[float] = Field(None, ge=0, description="Maximum budget (numeric, local currency)")
    currency: str = Field(..., min_length=3, max_length=3, description="Currency code (e.g. USD, EUR)")
    taxRate: Optional[float] = Field(None, ge=0.0, le=1.0, description="Applicable tax rate (0.0-1.0)")
    location: Optional[str] = Field(None, max_length=200, description="Region or country (for tax/currency context)")
    description: Optional[str] = Field(None, max_length=100000, description="Detailed description or requirements text")

    @validator("currency")
    def validate_currency(cls, v):
        if not v.isalpha() or not v.isupper():
            raise ValueError("Currency must be a 3-letter uppercase ISO 4217 code (e.g., USD, INR)")
        return v
