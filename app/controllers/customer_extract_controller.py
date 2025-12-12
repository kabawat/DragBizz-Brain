from typing import Dict, Any

from app.models.customer import CustomerExtractRequest, CustomerExtractResponse
from app.services.customer_extract_service import CustomerExtractService


class CustomerExtractController:
    """Controller for customer data extraction from natural language prompts."""

    def __init__(self):
        self.service = CustomerExtractService()

    def extract(self, request: CustomerExtractRequest) -> Dict[str, Any]:
        """
        Extract customer data from natural language prompt.
        
        Only extracts data explicitly mentioned in the prompt.
        Does not generate or invent any missing fields.
        """
        response = self.service.extract_customer_data(request)
        return response.model_dump()

