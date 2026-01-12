from typing import Any, Dict, Optional, Tuple
import json
import re
import logging

from fastapi import HTTPException

from app.models.supplier import SupplierExtractRequest, SupplierExtractResponse, SupplierPayload
from app.utils.ai import AIClient, parse_json_response
from app.constants.ai import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_TEMPERATURE, EXTRACTION_MAX_TOKENS

logger = logging.getLogger(__name__)

SUPPLIER_EXTRACTION_SYSTEM_PROMPT = """Extract supplier data. Return JSON only.

Schema:{"name":str|null,"agency":str|null,"phone":str|null,"email":str|null,"store":str|null,"address":str|null,"gstNumber":str|null,"extractedFields":["field1"]}

Rules: Extract only mentioned data. Missing=null. JSON only."""


class SupplierExtractService:
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
        
        if self._is_valid_value(extracted.get("agency")):
            payload["agency"] = str(extracted["agency"]).strip()
            self._add_field(extracted_fields, "agency")
        
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
        
        if self._is_valid_value(extracted.get("address")):
            payload["address"] = str(extracted["address"]).strip()
            self._add_field(extracted_fields, "address")
        
        if self._is_valid_value(extracted.get("gstNumber")):
            gst = str(extracted["gstNumber"]).strip().upper()
            # Basic GST validation (15 characters)
            if len(gst) == 15:
                payload["gstNumber"] = gst
                self._add_field(extracted_fields, "gstNumber")
        
        return payload, extracted_fields

    async def extract_supplier_data(self, request: SupplierExtractRequest) -> SupplierExtractResponse:
        logger.info(f"Extracting supplier data from prompt (length: {len(request.prompt)})")
        messages = [
            {"role": "system", "content": SUPPLIER_EXTRACTION_SYSTEM_PROMPT},
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
            return SupplierExtractResponse(
                success=True,
                payload=SupplierPayload(**payload_dict),
                message="Supplier data extracted successfully",
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
                detail=f"Failed to extract supplier data: {str(e)}"
            )

