from typing import Optional
from pydantic import BaseModel, Field


class CustomerExtractRequest(BaseModel):
    """Request model for customer data extraction from natural language prompt."""
    
    prompt: str = Field(..., description="Natural language prompt containing customer information")


class CustomerChatRequest(BaseModel):
    """Request model for conversational customer creation."""
    
    sessionId: Optional[str] = Field(None, description="Session ID for continuing conversation")
    prompt: str = Field(..., description="Natural language prompt containing customer information")
    store: Optional[str] = Field(None, description="Store ID (can be set in first turn)")


class CustomerPayload(BaseModel):
    """Customer payload structure matching retailer API format."""
    
    name: Optional[str] = Field(None, description="Customer name (extract only if mentioned)")
    phone: Optional[str] = Field(None, description="Phone number (extract only if mentioned)")
    email: Optional[str] = Field(None, description="Email address (extract only if mentioned)")
    store: Optional[str] = Field(None, description="Store ID (extract only if mentioned)")
    companyDetails: Optional[dict] = Field(None, description="Company details (extract only if mentioned)")
    addresses: Optional[dict] = Field(None, description="Addresses (extract only if mentioned)")


class CustomerExtractResponse(BaseModel):
    """Response model for customer extraction."""
    
    success: bool = Field(..., description="Whether extraction was successful")
    payload: Optional[CustomerPayload] = Field(None, description="Extracted customer payload")
    message: str = Field(..., description="Response message")
    extractedFields: list[str] = Field(default_factory=list, description="List of fields that were extracted from prompt")


class CustomerChatResponse(BaseModel):
    """Response model for conversational customer creation."""
    
    success: bool = Field(..., description="Whether operation was successful")
    sessionId: str = Field(..., description="Session ID for continuing conversation")
    message: str = Field(..., description="Conversational response message")
    type: str = Field(..., description="Response type: ask_for_missing_fields, ready_to_create, or completed")
    extractedData: Optional[CustomerPayload] = Field(None, description="Currently extracted customer data")
    missingFields: list[str] = Field(default_factory=list, description="List of missing required fields")
    status: str = Field(..., description="Current conversation status")

