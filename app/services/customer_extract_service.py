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
    
    # Optimized system prompt - minimal tokens
    SYSTEM_PROMPT = """Extract customer data from prompts. Extract ONLY mentioned fields. Use null if not mentioned. Return JSON.

Fields: name, phone, email, store, companyDetails{gstin,companyName}, addresses{billing,shipping{addressLine1,city,state,pincode,country,label}}

Output JSON:
{"name":null|string,"phone":null|string,"email":null|string,"store":null|string,"companyDetails":null|{"gstin":null|string,"companyName":null|string},"addresses":null|{"billing":null|{...},"shipping":null|{...}},"extractedFields":["field1",...]}

Example: "customer name rohan" → {"name":"rohan","phone":null,"email":null,"store":null,"companyDetails":null,"addresses":null,"extractedFields":["name"]}"""

    def __init__(self, http_client: HttpClient | None = None, settings=None):
        self.settings = settings or get_settings()
        self.http_client = http_client or HttpClient(timeout=self.REQUEST_TIMEOUT)

    @property
    def chat_url(self) -> str:
        return f"{self.BASE_URL}{self.CHAT_ENDPOINT}"

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

    def _prepare_extraction_prompt(self, user_prompt: str) -> str:
        """Prepare the user prompt with context."""
        return f'Extract: "{user_prompt}"'

    def _parse_ai_response(self, ai_response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse AI response and extract JSON."""
        content = ""
        try:
            # Get content from response
            content = ai_response.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            if not content:
                raise ValueError("Empty response from AI")
            
            # Try to extract JSON from response (might have markdown code blocks)
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                json_str = json_match.group(0)
            else:
                json_str = content.strip()
            
            # Remove markdown code block markers if present
            json_str = re.sub(r'^```json\s*', '', json_str)
            json_str = re.sub(r'^```\s*', '', json_str)
            json_str = re.sub(r'\s*```$', '', json_str)
            json_str = json_str.strip()
            
            # Parse JSON
            parsed = json.loads(json_str)
            return parsed
            
        except (json.JSONDecodeError, KeyError, IndexError, ValueError) as e:
            error_msg = f"Failed to parse AI response: {str(e)}"
            if content:
                error_msg += f". Response preview: {content[:200]}"
            raise HTTPException(
                status_code=500,
                detail=error_msg
            )

    def _validate_extracted_data(self, extracted: Dict[str, Any]) -> tuple[Dict[str, Any], list[str]]:
        """Validate and clean extracted data."""
        payload = {}
        extracted_fields = []
        
        # Extract store (only if mentioned in prompt)
        if extracted.get("store") and extracted["store"] != "null":
            payload["store"] = str(extracted["store"]).strip()
            extracted_fields.append("store")
        
        # Extract name (only if present and not null)
        if extracted.get("name") and extracted["name"] != "null":
            payload["name"] = str(extracted["name"]).strip()
            extracted_fields.append("name")
        
        # Extract phone (only if present and not null)
        if extracted.get("phone") and extracted["phone"] != "null":
            phone = str(extracted["phone"]).strip()
            # Remove any non-digit characters
            phone = re.sub(r'\D', '', phone)
            if phone:
                payload["phone"] = phone
                extracted_fields.append("phone")
        
        # Extract email (only if present and not null)
        if extracted.get("email") and extracted["email"] != "null":
            email = str(extracted["email"]).strip().lower()
            if email and "@" in email:
                payload["email"] = email
                extracted_fields.append("email")
        
        # Extract companyDetails (only if present and not null)
        company_details = extracted.get("companyDetails")
        if company_details and company_details != "null" and isinstance(company_details, dict):
            company_payload = {}
            if company_details.get("gstin") and company_details["gstin"] != "null":
                gstin = str(company_details["gstin"]).strip().upper()
                if gstin:
                    company_payload["gstin"] = gstin
                    extracted_fields.append("companyDetails.gstin")
            
            if company_details.get("companyName") and company_details["companyName"] != "null":
                company_name = str(company_details["companyName"]).strip()
                if company_name:
                    company_payload["companyName"] = company_name
                    extracted_fields.append("companyDetails.companyName")
            
            if company_payload:
                payload["companyDetails"] = company_payload
        
        # Extract addresses (only if present and not null)
        addresses = extracted.get("addresses")
        if addresses and addresses != "null" and isinstance(addresses, dict):
            address_payload = {}
            
            # Billing address
            billing = addresses.get("billing")
            if billing and billing != "null" and isinstance(billing, dict):
                billing_addr = {}
                for field in ["addressLine1", "city", "state", "pincode", "country", "label"]:
                    if billing.get(field) and billing[field] != "null":
                        billing_addr[field] = str(billing[field]).strip()
                        extracted_fields.append(f"addresses.billing.{field}")
                if billing_addr:
                    address_payload["billing"] = billing_addr
            
            # Shipping address
            shipping = addresses.get("shipping")
            if shipping and shipping != "null" and isinstance(shipping, dict):
                shipping_addr = {}
                for field in ["addressLine1", "city", "state", "pincode", "country", "label"]:
                    if shipping.get(field) and shipping[field] != "null":
                        shipping_addr[field] = str(shipping[field]).strip()
                        extracted_fields.append(f"addresses.shipping.{field}")
                if shipping_addr:
                    address_payload["shipping"] = shipping_addr
            
            if address_payload:
                payload["addresses"] = address_payload
        
        return payload, extracted_fields

    def _is_rate_limit_error(self, error: HTTPException) -> bool:
        """Check if error is a rate limit error by parsing OpenRouter error format."""
        error_detail = str(error.detail)
        error_str = error_detail.lower()
        
        # Try to parse JSON error if present (OpenRouter returns JSON errors)
        try:
            # Check if error_detail is JSON string
            if error_detail.strip().startswith('{'):
                error_dict = json.loads(error_detail)
                if isinstance(error_dict, dict):
                    error_info = error_dict.get("error", {})
                    if isinstance(error_info, dict):
                        error_code = error_info.get("code")
                        error_message = str(error_info.get("message", "")).lower()
                        # Check code 429 or rate limit in message
                        if error_code == 429 or "rate" in error_message or "rate-limited" in error_message:
                            return True
        except (json.JSONDecodeError, KeyError, AttributeError):
            pass
        
        # Check for rate limit indicators in error string
        is_rate_limit = (
            error.status_code == 429 or 
            "rate" in error_str or 
            "rate-limited" in error_str or
            "429" in error_str or
            "temporarily" in error_str
        )
        
        return is_rate_limit

    def _call_ai_with_fallback(self, messages: list, model: str) -> Dict[str, Any]:
        """Call AI service with automatic fallback on rate limit errors."""
        request_data = {
            "model": model,
            "messages": messages,
            "temperature": self.DEFAULT_TEMPERATURE,
            "max_tokens": self.DEFAULT_MAX_TOKENS
        }
        
        headers = self._build_headers()
        
        try:
            return self.http_client.post(
                url=self.chat_url,
                headers=headers,
                json=request_data
            )
        except HTTPException as e:
            # Always re-raise, we'll check in the calling method
            raise

    def extract_customer_data(self, request: CustomerExtractRequest) -> CustomerExtractResponse:
        """Extract customer data from natural language prompt."""
        # Prepare messages for AI
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": self._prepare_extraction_prompt(request.prompt)}
        ]
        
        # Try models in order: DEFAULT -> FALLBACK -> SECONDARY_FALLBACK
        models_to_try = [
            self.DEFAULT_MODEL,
            self.FALLBACK_MODEL,
            self.SECONDARY_FALLBACK
        ]
        
        ai_response = None
        last_error = None
        
        for model in models_to_try:
            try:
                ai_response = self._call_ai_with_fallback(messages, model)
                break
            except HTTPException as e:
                last_error = e
                is_rate_limit = self._is_rate_limit_error(e)
                
                # If rate limit and more models to try, continue to next model
                if is_rate_limit and model != models_to_try[-1]:
                    continue  # Try next model
                else:
                    # If last model and rate limited, raise with clear message
                    if model == models_to_try[-1] and is_rate_limit:
                        raise HTTPException(
                            status_code=429,
                            detail=f"All AI models are rate-limited. Please try again later. Last error: {str(e.detail)}"
                        )
                    # For non-rate-limit errors, raise immediately
                    raise
        
        if ai_response is None:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to get response from AI service: {str(last_error)}"
            )
        
        try:
            # Parse AI response
            extracted = self._parse_ai_response(ai_response)
            
            # Validate and clean extracted data
            payload_dict, extracted_fields = self._validate_extracted_data(extracted)
            
            # Create payload model
            payload = CustomerPayload(**payload_dict)
            
            return CustomerExtractResponse(
                success=True,
                payload=payload,
                message="Customer data extracted successfully",
                extractedFields=extracted_fields
            )
            
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to extract customer data: {str(e)}"
            )

