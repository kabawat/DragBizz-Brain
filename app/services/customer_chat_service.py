from typing import Any, Dict, Optional
import logging

from fastapi import HTTPException

from app.models.customer import CustomerChatRequest, CustomerChatResponse, CustomerExtractRequest, CustomerPayload
from app.services.customer_extract_service import CustomerExtractService
from app.services.session_service import SessionService
from app.utils.ai import AIClient, parse_text_response, detect_language, build_conversation_prompt
from app.utils.validation import is_valid_object_id
from app.constants.ai import DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS

logger = logging.getLogger(__name__)


class CustomerChatService:
    def __init__(self):
        self.extract_service = CustomerExtractService()
        self.session_service = SessionService()
        self.ai_client = AIClient()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    def _merge_data(self, existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        merged = existing.copy()
        for field in ["name", "phone", "email", "store"]:
            if new.get(field):
                merged[field] = new[field]
        if new.get("companyDetails"):
            if not merged.get("companyDetails"):
                merged["companyDetails"] = {}
            merged["companyDetails"].update(new["companyDetails"])
        if new.get("addresses"):
            if not merged.get("addresses"):
                merged["addresses"] = {}
            for addr_type in ["billing", "shipping"]:
                if new["addresses"].get(addr_type):
                    if not merged["addresses"].get(addr_type):
                        merged["addresses"][addr_type] = {}
                    merged["addresses"][addr_type].update(new["addresses"][addr_type])
        
        return merged
    
    def _check_required_fields(self, data: Dict[str, Any], store: Optional[str]) -> list[str]:
        missing = []
        if not data.get("name") or len(str(data.get("name", "")).strip()) < 2:
            missing.append("name")
        
        if not data.get("phone") and not data.get("email"):
            missing.append("contact")
        store_value = store or data.get("store")
        if not store_value:
            missing.append("store")
        elif not is_valid_object_id(store_value):
            missing.append("store")
            logger.warning(f"Invalid store ID format: {store_value}")
        
        return missing
    
    async def _get_fallback_message(self, missing_fields: list[str], user_prompt: str) -> str:
        try:
            user_language_hint = detect_language(user_prompt)
            conversation_prompt = build_conversation_prompt(user_language_hint)
            
            missing_str = ", ".join(missing_fields)
            ai_user_prompt = f"User asked: \"{user_prompt[:100]}\". Missing fields: {missing_str}. Ask user to provide missing information. Respond in EXACT same language and script as user's query: \"{user_prompt[:50]}\""
            
            messages = [
                {"role": "system", "content": conversation_prompt},
                {"role": "user", "content": ai_user_prompt}
            ]
            
            ai_response = await self.ai_client.call_with_fallback(
                messages=messages,
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
                use_cache=False
            )
            
            if ai_response:
                content = parse_text_response(ai_response)
                if content:
                    return content
        except Exception as e:
            logger.warning(f"Failed to generate AI fallback message: {str(e)}")
        
        if "contact" in missing_fields:
            return "Please provide customer email ID or phone number"
        elif "name" in missing_fields:
            return "Please provide customer name"
        elif "store" in missing_fields:
            return "Please provide store ID"
        else:
            return "Some required information is missing, please provide"
    
    async def _get_fallback_success_message(self, user_prompt: str) -> str:
        try:
            user_language_hint = detect_language(user_prompt)
            conversation_prompt = build_conversation_prompt(user_language_hint)
            
            ai_user_prompt = f"User asked: \"{user_prompt[:100]}\". All required customer details are now available. Confirm this to the user. Respond in EXACT same language and script as user's query: \"{user_prompt[:50]}\""
            
            messages = [
                {"role": "system", "content": conversation_prompt},
                {"role": "user", "content": ai_user_prompt}
            ]
            
            ai_response = await self.ai_client.call_with_fallback(
                messages=messages,
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
                use_cache=False
            )
            
            if ai_response:
                content = parse_text_response(ai_response)
                if content:
                    return content
        except Exception as e:
            logger.warning(f"Failed to generate AI success fallback message: {str(e)}")
        
        return "All required details are available. Ready to create customer."
    
    async def _get_fallback_error_message(self, user_prompt: str, error_detail: str = "") -> str:
        try:
            user_language_hint = detect_language(user_prompt)
            conversation_prompt = build_conversation_prompt(user_language_hint)
            
            error_text = f"Error: {error_detail}" if error_detail else "An error occurred"
            ai_user_prompt = f"User asked: \"{user_prompt[:100]}\". {error_text}. Ask user to try again or provide information differently. Respond in EXACT same language and script as user's query: \"{user_prompt[:50]}\""
            
            messages = [
                {"role": "system", "content": conversation_prompt},
                {"role": "user", "content": ai_user_prompt}
            ]
            
            ai_response = await self.ai_client.call_with_fallback(
                messages=messages,
                temperature=DEFAULT_TEMPERATURE,
                max_tokens=DEFAULT_MAX_TOKENS,
                use_cache=False
            )
            
            if ai_response:
                content = parse_text_response(ai_response)
                if content:
                    return content
        except Exception as e:
            logger.warning(f"Failed to generate AI error fallback message: {str(e)}")
        
        return "An error occurred. Please try your request again or provide information in a different way."
    
    async def _generate_ai_response_message(self, missing_fields: list[str], extracted_data: Dict[str, Any], user_prompt: str) -> str:
        user_language_hint = detect_language(user_prompt)
        conversation_prompt = build_conversation_prompt(user_language_hint)
        
        missing = []
        if "name" in missing_fields:
            missing.append("name")
        if "contact" in missing_fields:
            missing.append("contact")
        if "store" in missing_fields:
            missing.append("store")
        
        have = []
        if extracted_data.get("name"):
            have.append(f"name:{extracted_data['name']}")
        if extracted_data.get("phone"):
            have.append("phone")
        elif extracted_data.get("email"):
            have.append("email")
        
        ai_user_prompt = f"Missing:{','.join(missing)}. Have:{','.join(have) if have else 'none'}. User query: \"{user_prompt[:80]}\". IMPORTANT: Respond in the EXACT same language and script as the user's query. Use the same language as: \"{user_prompt[:50]}\""
        
        messages = [
            {"role": "system", "content": conversation_prompt},
            {"role": "user", "content": ai_user_prompt}
        ]
        
        ai_response = await self.ai_client.call_with_fallback(
            messages=messages,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            use_cache=True
        )
        
        if ai_response:
            content = parse_text_response(ai_response)
            if content:
                return content
        
        return await self._get_fallback_message(missing_fields, user_prompt)
    
    async def _generate_ai_success_message(self, extracted_data: Dict[str, Any], user_prompt: str) -> str:
        user_language_hint = detect_language(user_prompt)
        conversation_prompt = build_conversation_prompt(user_language_hint)
        
        name = extracted_data.get('name', 'N/A')
        contact = extracted_data.get('email') or extracted_data.get('phone', 'N/A')
        ai_user_prompt = f"Ready. Name:{name}, Contact:{contact}. User query: \"{user_prompt[:80]}\". IMPORTANT: Respond in the EXACT same language and script as the user's query. Use the same language as: \"{user_prompt[:50]}\""
        
        messages = [
            {"role": "system", "content": conversation_prompt},
            {"role": "user", "content": ai_user_prompt}
        ]
        
        ai_response = await self.ai_client.call_with_fallback(
            messages=messages,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            use_cache=True
        )
        
        if ai_response:
            content = parse_text_response(ai_response)
            if content:
                return content
        
        return await self._get_fallback_success_message(user_prompt)
    
    async def _generate_ai_error_message(self, error_detail: str, user_prompt: str) -> str:
        user_language_hint = detect_language(user_prompt)
        conversation_prompt = build_conversation_prompt(user_language_hint)
        
        ai_user_message = f"Error occurred. User query: \"{user_prompt[:80]}\". Error: {error_detail[:80]}. IMPORTANT: Respond in the EXACT same language and script as the user's query. Ask user to retry. Use the same language as: \"{user_prompt[:50]}\""
        
        messages = [
            {"role": "system", "content": conversation_prompt},
            {"role": "user", "content": ai_user_message}
        ]
        
        ai_response = await self.ai_client.call_with_fallback(
            messages=messages,
            temperature=DEFAULT_TEMPERATURE,
            max_tokens=DEFAULT_MAX_TOKENS,
            use_cache=True
        )
        
        if ai_response:
            content = parse_text_response(ai_response)
            if content:
                return content
        
        return await self._get_fallback_error_message(user_prompt, error_detail)
    
    async def handle_conversation(self, request: CustomerChatRequest, user_id: Optional[str] = None, token: Optional[str] = None) -> CustomerChatResponse:
        if not request.prompt or not isinstance(request.prompt, str):
            raise HTTPException(
                status_code=400,
                detail="Prompt is required and must be a non-empty string"
            )
        
        prompt = request.prompt.strip()
        if len(prompt) < 2:
            raise HTTPException(
                status_code=400,
                detail="Prompt must be at least 2 characters long"
            )
        
        logger.info(f"Handling conversation request. Session: {request.sessionId}, Prompt length: {len(prompt)}")
        
        session_id = request.sessionId
        session = None
        
        if session_id:
            session = self.session_service.get_session(session_id)
            if not session:
                logger.info(f"Session {session_id} expired, creating new session")
                session_id = None
        
        if not session_id:
            session_id = self.session_service.create_session()
            session = self.session_service.get_session(session_id)
            logger.info(f"Created new session: {session_id}")
        
        extract_request = CustomerExtractRequest(prompt=prompt)
        
        try:
            extract_response = await self.extract_service.extract_customer_data(extract_request)
            logger.debug(f"Extracted {len(extract_response.extractedFields)} fields from prompt")
        except HTTPException as e:
            logger.error(f"Extraction error: {e.status_code} - {e.detail}")
            error_message = await self._generate_ai_error_message(str(e.detail), prompt)
            return CustomerChatResponse(
                success=False,
                sessionId=session_id,
                message=error_message,
                type="extraction_error",
                extractedData=None,
                missingFields=[],
                status="error"
            )
        
        existing_data = session.get("extracted_data", {})
        
        new_data = {}
        if extract_response.payload:
            new_data = extract_response.payload.model_dump(exclude_none=True)
        
        merged_data = self._merge_data(existing_data, new_data)
        
        store = request.store or merged_data.get("store")
        
        missing_fields = self._check_required_fields(merged_data, store)
        
        self.session_service.update_session(session_id, {
            "extracted_data": merged_data,
            "store": store
        })
        
        payload = CustomerPayload(**merged_data)
        
        if missing_fields:
            logger.info(f"Missing fields: {missing_fields}")
            message = await self._generate_ai_response_message(missing_fields, merged_data, prompt)
            
            if "contact" in missing_fields:
                status = "waiting_for_contact"
            elif "name" in missing_fields:
                status = "waiting_for_name"
            elif "store" in missing_fields:
                status = "waiting_for_store"
            else:
                status = "waiting_for_fields"
            
            return CustomerChatResponse(
                success=False,
                sessionId=session_id,
                message=message,
                type="ask_for_missing_fields",
                extractedData=payload,
                missingFields=missing_fields,
                status=status
            )
        else:
            logger.info("All required fields present, generating success message")
            message = await self._generate_ai_success_message(merged_data, prompt)
            
            return CustomerChatResponse(
                success=True,
                sessionId=session_id,
                message=message,
                type="ready_to_create",
                extractedData=payload,
                missingFields=[],
                status="ready_to_create"
            )
