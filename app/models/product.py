from typing import Optional, List
from pydantic import BaseModel, Field


class GstInfo(BaseModel):
    """GST information for product."""
    
    isGstApplicable: bool = Field(True, description="Whether GST is applicable")
    gstRate: Optional[float] = Field(None, description="GST rate percentage")
    gstType: Optional[str] = Field(None, description="GST type (CGST_SGST, IGST, etc.)")
    hsnCode: Optional[str] = Field(None, description="HSN code")
    sacCode: Optional[str] = Field(None, description="SAC code")
    cessRate: Optional[float] = Field(0, description="CESS rate")


class Specification(BaseModel):
    """Product specification item."""
    
    name: str = Field(..., description="Specification name")
    value: str = Field(..., description="Specification value")
    unit: Optional[str] = Field(None, description="Specification unit")


class Content(BaseModel):
    """Product content information."""
    
    shortDescription: Optional[str] = Field(None, description="Short product description")
    longDescription: Optional[str] = Field(None, description="Long product description")
    tags: Optional[List[str]] = Field(default_factory=list, description="Product tags")
    features: Optional[List[str]] = Field(default_factory=list, description="Product features")
    specifications: Optional[List[Specification]] = Field(default_factory=list, description="Product specifications")


class ProductPayload(BaseModel):
    """Product payload structure matching retailer API format."""
    
    # Required fields
    name: str = Field(..., description="Product name")
    mrp: float = Field(..., description="Maximum Retail Price")
    sellingPrice: float = Field(..., description="Selling price")
    
    # Optional but commonly needed fields
    store: Optional[str] = Field(None, description="Store ID")
    category: Optional[str] = Field(None, description="Category ID")
    
    # Optional basic fields
    brand: Optional[str] = Field(None, description="Product brand")
    subcategory: Optional[str] = Field(None, description="Subcategory ID")
    basePrice: Optional[float] = Field(None, description="Base price")
    discount: Optional[float] = Field(None, description="Discount percentage")
    currency: Optional[str] = Field("INR", description="Currency code")
    uom: Optional[str] = Field(None, description="Unit of measurement")
    barcode: Optional[str] = Field(None, description="Product barcode")
    sku: Optional[str] = Field(None, description="SKU code")
    
    # GST information
    isGstIncluded: Optional[bool] = Field(True, description="Whether GST is included in price")
    gstInfo: Optional[GstInfo] = Field(None, description="GST information")
    
    # Content information
    content: Optional[Content] = Field(None, description="Product content information")


class ProductExtractRequest(BaseModel):
    """Request model for product data extraction from image."""
    
    store: Optional[str] = Field(None, description="Store ID (optional, can be extracted from image)")
    category: Optional[str] = Field(None, description="Category ID (optional, can be extracted from image)")


class ProductExtractResponse(BaseModel):
    """Response model for product extraction."""
    
    success: bool = Field(..., description="Whether extraction was successful")
    payload: Optional[ProductPayload] = Field(None, description="Extracted product payload")
    message: str = Field(..., description="Response message")

