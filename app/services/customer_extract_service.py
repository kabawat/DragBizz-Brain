from typing import Any, Dict, Optional, Tuple
import json
import re
import logging

from fastapi import HTTPException

from app.models.customer import CustomerExtractRequest, CustomerExtractResponse, CustomerPayload
from app.utils.ai import AIClient, parse_json_response
from app.constants.ai import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_TEMPERATURE, EXTRACTION_MAX_TOKENS

logger = logging.getLogger(__name__)


class CustomerExtractService:
    def __init__(self, ai_client: Optional[AIClient] = None):
        self.ai_client = ai_client or AIClient()

    def _is_valid_value(self, value: Any) -> bool:
        """Check if value is valid (not None, null, or empty string)."""
        return value not in [None, "null", ""]
    
    def _add_field(self, fields: list[str], field_name: str):
        """Add field to extracted fields list if not already present."""
        if field_name not in fields:
            fields.append(field_name)
    
    def _validate_extracted_data(self, extracted: Dict[str, Any]) -> Tuple[Dict[str, Any], list[str]]:
        payload = {}
        extracted_fields = extracted.get("extractedFields", []) if isinstance(extracted.get("extractedFields"), list) else []
        
        if self._is_valid_value(extracted.get("name")):
            payload["name"] = str(extracted["name"]).strip()
            self._add_field(extracted_fields, "name")
        
        if self._is_valid_value(extracted.get("store")):
            payload["store"] = str(extracted["store"]).strip()
            self._add_field(extracted_fields, "store")
        
        if self._is_valid_value(extracted.get("phone")):
            phone = re.sub(r'\D', '', str(extracted["phone"]))
            if phone and 10 <= len(phone) <= 15:
                payload["phone"] = phone
                self._add_field(extracted_fields, "phone")
        
        if self._is_valid_value(extracted.get("email")):
            email = str(extracted["email"]).strip().lower()
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if re.match(email_pattern, email):
                payload["email"] = email
                self._add_field(extracted_fields, "email")
        
        company_details = extracted.get("companyDetails")
        if self._is_valid_value(company_details) and isinstance(company_details, dict):
            company_payload = {}
            if self._is_valid_value(company_details.get("gstin")):
                company_payload["gstin"] = str(company_details["gstin"]).strip().upper()
                self._add_field(extracted_fields, "companyDetails.gstin")
            if self._is_valid_value(company_details.get("companyName")):
                company_payload["companyName"] = str(company_details["companyName"]).strip()
                self._add_field(extracted_fields, "companyDetails.companyName")
            if company_payload:
                payload["companyDetails"] = company_payload
        
        addresses = extracted.get("addresses")
        if self._is_valid_value(addresses) and isinstance(addresses, dict):
            address_payload = {}
            for addr_type in ["billing", "shipping"]:
                addr = addresses.get(addr_type)
                if self._is_valid_value(addr) and isinstance(addr, dict):
                    addr_data = {}
                    for field in ["addressLine1", "city", "state", "pincode", "country", "label"]:
                        if self._is_valid_value(addr.get(field)):
                            addr_data[field] = str(addr[field]).strip()
                            self._add_field(extracted_fields, f"addresses.{addr_type}.{field}")
                    if addr_data:
                        address_payload[addr_type] = addr_data
            if address_payload:
                payload["addresses"] = address_payload
        
        return payload, extracted_fields

    async def extract_customer_data(self, request: CustomerExtractRequest) -> CustomerExtractResponse:
        logger.info(f"Extracting customer data from prompt (length: {len(request.prompt)})")
        messages = [
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": f'Extract: "{request.prompt}"'}
        ]
        
        try:
            ai_response = await self.ai_client.call_with_fallback(
                messages=messages,
                temperature=EXTRACTION_TEMPERATURE,
                max_tokens=EXTRACTION_MAX_TOKENS,
                use_cache=True,
                response_format={"type": "json_object"}
            )
            
            if not ai_response:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to get response from AI service"
                )
            
            extracted = parse_json_response(ai_response)
            payload_dict, extracted_fields = self._validate_extracted_data(extracted)
            
            logger.info(f"Successfully extracted {len(extracted_fields)} fields: {extracted_fields}")
            return CustomerExtractResponse(
                success=True,
                payload=CustomerPayload(**payload_dict),
                message="Customer data extracted successfully",
                extractedFields=extracted_fields
            )
            
        except HTTPException as e:
            if e.status_code == 429:
                logger.error("All AI models are rate-limited")
                raise HTTPException(
                    status_code=429,
                    detail="All AI models are rate-limited. Please try again later."
                )
            raise
        except Exception as e:
            logger.error(f"Extraction failed: {str(e)}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract customer data: {str(e)}"
            )

