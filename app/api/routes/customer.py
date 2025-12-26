from fastapi import APIRouter

from app.controllers.customer_extract_controller import CustomerExtractController
from app.models.customer import CustomerExtractRequest, CustomerExtractResponse

router = APIRouter(tags=["customer"])
controller = CustomerExtractController()


@router.post("/extract", response_model=CustomerExtractResponse)
def extract_customer(payload: CustomerExtractRequest):
    return controller.extract(payload)

