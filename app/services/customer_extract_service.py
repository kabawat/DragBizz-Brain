from typing import Any, Dict
import json
import re

from fastapi import HTTPException

from app.config.settings import get_settings
from app.models.customer import CustomerExtractRequest, CustomerExtractResponse, CustomerPayload
from app.services.http import HttpClient


class CustomerExtractService:
    """Service for extracting customer data from natural language prompts."""
    
    BASE_URL = "https://openrouter.ai/api/v1"
    CHAT_ENDPOINT = "/chat/completions"
    DEFAULT_MODEL = "openai/gpt-4o-mini"  # More reliable model
    FALLBACK_MODEL = "google/gemini-2.0-flash-exp:free"  # Free fallback
    SECONDARY_FALLBACK = "meta-llama/llama-3.2-3b-instruct:free"  # Another free option
    DEFAULT_TEMPERATURE = 0.1  # Low temperature for strict extraction
    DEFAULT_MAX_TOKENS = 500
    REQUEST_TIMEOUT = 30
    
    # Optimized system prompt - strict extraction rules with consistent format
    SYSTEM_PROMPT = """Extract customer data from prompt. Return ONLY valid JSON starting with { and ending with }. No markdown, no text outside JSON.

Schema:
{
  "name": string|null,
  "phone": string|null (digits only),
  "email": string|null (lowercase),
  "store": string|null,
  "companyDetails": {"gstin": string|null (uppercase), "companyName": string|null}|null,
  "addresses": {
    "billing": {"addressLine1", "city", "state", "pincode", "country", "label": string|null}|null,
    "shipping": {"addressLine1", "city", "state", "pincode", "country", "label": string|null}|null
  }|null,
  "extractedFields": ["field1", ...]
}

Rules: Extract only mentioned data. Use exact field names. Missing data = null. Return JSON only."""

    def __init__(self, http_client: HttpClient | None = None, settings=None):
        self.settings = settings or get_settings()
        self.http_client = http_client or HttpClient(timeout=self.REQUEST_TIMEOUT)

    def _build_headers(self) -> Dict[str, str]:
        """Build headers for OpenRouter API request."""
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
        }
        if self.settings.openrouter_http_referer:
            headers["HTTP-Referer"] = self.settings.openrouter_http_referer
        if self.settings.openrouter_title:
            headers["X-Title"] = self.settings.openrouter_title
        return headers

    def _parse_ai_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse AI response and extract JSON."""
        try:
            content = ai_response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not content:
                raise ValueError("Empty response from AI")
            
            # Remove markdown if present (fallback for models that don't support json_object)
            json_str = re.sub(r'^```json\s*|^```\s*|\s*```$', '', content.strip())
            return json.loads(json_str)
            
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to parse AI response: {str(e)}"
            )

    def _is_valid_value(self, value: Any) -> bool:
        """Check if value is valid (not None, null, or empty string)."""
        return value not in [None, "null", ""]
    
    def _add_field(self, fields: list[str], field_name: str):
        """Add field to extracted fields list if not already present."""
        if field_name not in fields:
            fields.append(field_name)
    
    def _validate_extracted_data(self, extracted: Dict[str, Any]) -> tuple[Dict[str, Any], list[str]]:
        """Validate and clean extracted data."""
        payload = {}
        extracted_fields = extracted.get("extractedFields", []) if isinstance(extracted.get("extractedFields"), list) else []
        
        # Simple fields
        for field in ["store", "name"]:
            if self._is_valid_value(extracted.get(field)):
                payload[field] = str(extracted[field]).strip()
                self._add_field(extracted_fields, field)
        
        # Phone (remove non-digits)
        if self._is_valid_value(extracted.get("phone")):
            phone = re.sub(r'\D', '', str(extracted["phone"]))
            if phone:
                payload["phone"] = phone
                self._add_field(extracted_fields, "phone")
        
        # Email (lowercase)
        if self._is_valid_value(extracted.get("email")):
            email = str(extracted["email"]).strip().lower()
            if "@" in email:
                payload["email"] = email
                self._add_field(extracted_fields, "email")
        
        # Company details
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
        
        # Addresses
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

    def _is_rate_limit_error(self, error: HTTPException) -> bool:
        """Check if error is a rate limit error."""
        if error.status_code == 429:
            return True
        
        error_str = str(error.detail).lower()
        rate_limit_keywords = ["rate", "rate-limited", "429", "temporarily"]
        if any(keyword in error_str for keyword in rate_limit_keywords):
            return True
        
        # Check JSON error format
        try:
            if str(error.detail).strip().startswith('{'):
                error_dict = json.loads(str(error.detail))
                error_code = error_dict.get("error", {}).get("code")
                if error_code == 429:
                    return True
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass
        
        return False

    def extract_customer_data(self, request: CustomerExtractRequest) -> CustomerExtractResponse:
        """Extract customer data from natural language prompt."""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f'Extract: "{request.prompt}"'}
        ]
        
        models_to_try = [self.DEFAULT_MODEL, self.FALLBACK_MODEL, self.SECONDARY_FALLBACK]
        last_error = None
        
        for model in models_to_try:
            try:
                request_data = {
                    "model": model,
                    "messages": messages,
                    "temperature": self.DEFAULT_TEMPERATURE,
                    "max_tokens": self.DEFAULT_MAX_TOKENS,
                    "response_format": {"type": "json_object"}
                }
                ai_response = self.http_client.post(
                    url=f"{self.BASE_URL}{self.CHAT_ENDPOINT}",
                    headers=self._build_headers(),
                    json=request_data
                )
                
                extracted = self._parse_ai_response(ai_response)
                payload_dict, extracted_fields = self._validate_extracted_data(extracted)
                
                return CustomerExtractResponse(
                    success=True,
                    payload=CustomerPayload(**payload_dict),
                    message="Customer data extracted successfully",
                    extractedFields=extracted_fields
                )
                
            except HTTPException as e:
                last_error = e
                is_rate_limit = self._is_rate_limit_error(e)
                
                if is_rate_limit and model != models_to_try[-1]:
                    continue
                elif is_rate_limit and model == models_to_try[-1]:
                    raise HTTPException(
                        status_code=429,
                        detail=f"All AI models are rate-limited. Please try again later."
                    )
                else:
                    raise
        
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get response from AI service: {str(last_error)}"
        )

