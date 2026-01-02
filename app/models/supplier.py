from typing import Optional
from pydantic import BaseModel, Field


class SupplierExtractRequest(BaseModel):
    """Request model for supplier data extraction from natural language prompt."""
    
    prompt: str = Field(..., description="Natural language prompt containing supplier information")


class SupplierChatRequest(BaseModel):
    """Request model for conversational supplier creation."""
    
    sessionId: Optional[str] = Field(None, description="Session ID for continuing conversation")
    prompt: str = Field(..., description="Natural language prompt containing supplier information")
    store: Optional[str] = Field(None, description="Store ID (can be set in first turn)")


class SupplierPayload(BaseModel):
    """Supplier payload structure matching retailer API format."""
    
    name: Optional[str] = Field(None, description="Supplier name (extract only if mentioned)")
    agency: Optional[str] = Field(None, description="Supplier agency name (extract only if mentioned)")
    phone: Optional[str] = Field(None, description="Phone number (extract only if mentioned)")
    email: Optional[str] = Field(None, description="Email address (extract only if mentioned)")
    store: Optional[str] = Field(None, description="Store ID (extract only if mentioned)")
    address: Optional[str] = Field(None, description="Physical address (extract only if mentioned)")
    gstNumber: Optional[str] = Field(None, description="GST number (extract only if mentioned)")


class SupplierExtractResponse(BaseModel):
    """Response model for supplier extraction."""
    
    success: bool = Field(..., description="Whether extraction was successful")
    payload: Optional[SupplierPayload] = Field(None, description="Extracted supplier payload")
    message: str = Field(..., description="Response message")
    extractedFields: list[str] = Field(default_factory=list, description="List of fields that were extracted from prompt")


class SupplierChatResponse(BaseModel):
    """Response model for conversational supplier creation."""
    
    success: bool = Field(..., description="Whether operation was successful")
    sessionId: str = Field(..., description="Session ID for continuing conversation")
    message: str = Field(..., description="Conversational response message")
    type: str = Field(..., description="Response type: ask_for_missing_fields, ready_to_create, or completed")
    extractedData: Optional[SupplierPayload] = Field(None, description="Currently extracted supplier data")
    missingFields: list[str] = Field(default_factory=list, description="List of missing required fields")
    status: str = Field(..., description="Current conversation status")

