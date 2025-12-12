from typing import Optional
from pydantic import BaseModel, Field


class CustomerExtractRequest(BaseModel):
    """Request model for customer data extraction from natural language prompt."""
    
    prompt: str = Field(..., description="Natural language prompt containing customer information")


class CustomerPayload(BaseModel):
    """Customer payload structure matching retailer API format."""
    
    name: Optional[str] = Field(None, description="Customer name (extract only if mentioned)")
    phone: Optional[str] = Field(None, description="Phone number (extract only if mentioned)")
    email: Optional[str] = Field(None, description="Email address (extract only if mentioned)")
    companyDetails: Optional[dict] = Field(None, description="Company details (extract only if mentioned)")
    addresses: Optional[dict] = Field(None, description="Addresses (extract only if mentioned)")


class CustomerExtractResponse(BaseModel):
    """Response model for customer extraction."""
    
    success: bool = Field(..., description="Whether extraction was successful")
    payload: Optional[CustomerPayload] = Field(None, description="Extracted customer payload")
    message: str = Field(..., description="Response message")
    extractedFields: list[str] = Field(default_factory=list, description="List of fields that were extracted from prompt")

