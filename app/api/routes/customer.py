from fastapi import APIRouter

from app.controllers.customer_extract_controller import CustomerExtractController
from app.models.customer import CustomerExtractRequest, CustomerExtractResponse

router = APIRouter(tags=["customer"])
controller = CustomerExtractController()


@router.post("/extract", response_model=CustomerExtractResponse)
def extract_customer(payload: CustomerExtractRequest):
    """
    Extract customer data from natural language prompt.
    
    This endpoint extracts ONLY the data explicitly mentioned in the prompt.
    It does NOT generate, invent, or create any missing data.
    
    Example prompts:
    - "create a new customer name rakesh phone 9866786756"
    - "customer banao rohan naam ka"
    - "add customer name john email john@example.com phone 9876543210"
    
    Returns a payload in the exact format expected by the retailer API.
    """
    return controller.extract(payload)

