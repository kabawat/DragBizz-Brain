from typing import Any, Dict, Optional
import logging

from fastapi import HTTPException

from app.models.supplier import SupplierChatRequest, SupplierChatResponse, SupplierExtractRequest, SupplierPayload
from app.services.supplier_extract_service import SupplierExtractService
from app.services.session_service import SessionService
from app.utils.ai import AIClient, parse_text_response, detect_language, build_conversation_prompt
from app.utils.validation import is_valid_object_id
from app.constants.ai import DEFAULT_TEMPERATURE, DEFAULT_MAX_TOKENS

logger = logging.getLogger(__name__)


class SupplierChatService:
    def __init__(self):
        self.extract_service = SupplierExtractService()
        self.session_service = SessionService()
        self.ai_client = AIClient()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
    
    def _merge_data(self, existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        merged = existing.copy()
        for field in ["name", "agency", "phone", "email", "store", "address", "gstNumber"]:
            if new.get(field):
                merged[field] = new[field]
        
        return merged
    
    def _check_required_fields(self, data: Dict[str, Any], store: Optional[str]) -> list[str]:
        missing = []
        if not data.get("name") or len(str(data.get("name", "")).strip()) < 2:
            missing.append("name")
        
        if not data.get("agency") or len(str(data.get("agency", "")).strip()) < 2:
            missing.append("agency")
        
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
            return "Please provide supplier email ID or phone number"
        elif "name" in missing_fields:
            return "Please provide supplier name"
        elif "agency" in missing_fields:
            return "Please provide supplier agency name"
        elif "store" in missing_fields:
            return "Please provide store ID"
        else:
            return "Some required information is missing, please provide"
    
    async def _get_fallback_success_message(self, user_prompt: str) -> str:
        try:
            user_language_hint = detect_language(user_prompt)
            conversation_prompt = build_conversation_prompt(user_language_hint)
            
            ai_user_prompt = f"User asked: \"{user_prompt[:100]}\". All required supplier details are now available. Confirm this to the user. Respond in EXACT same language and script as user's query: \"{user_prompt[:50]}\""
            
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
        
        return "All required details are available. Ready to create supplier."
    
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
        if "agency" in missing_fields:
            missing.append("agency")
        if "contact" in missing_fields:
            missing.append("contact")
        if "store" in missing_fields:
            missing.append("store")
        
        have = []
        if extracted_data.get("name"):
            have.append(f"name:{extracted_data['name']}")
        if extracted_data.get("agency"):
            have.append(f"agency:{extracted_data['agency']}")
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
        agency = extracted_data.get('agency', 'N/A')
        contact = extracted_data.get('email') or extracted_data.get('phone', 'N/A')
        ai_user_prompt = f"Ready. Name:{name}, Agency:{agency}, Contact:{contact}. User query: \"{user_prompt[:80]}\". IMPORTANT: Respond in the EXACT same language and script as the user's query. Use the same language as: \"{user_prompt[:50]}\""
        
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
    
    async def handle_conversation(self, request: SupplierChatRequest, user_id: Optional[str] = None, token: Optional[str] = None) -> SupplierChatResponse:
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
        
        logger.info(f"Handling supplier conversation request. Session: {request.sessionId}, Prompt length: {len(prompt)}")
        
        session_id = request.sessionId
        session = None
        
        if session_id:
            session = await self.session_service.get_session(session_id)
            if not session:
                logger.info(f"Session {session_id} expired, creating new session")
                session_id = None
        
        if not session_id:
            session_id = await self.session_service.create_session()
            session = await self.session_service.get_session(session_id)
            if not session:
                logger.error(f"Failed to retrieve session {session_id} after creation")
                raise HTTPException(
                    status_code=503,
                    detail="Session service temporarily unavailable. Please try again."
                )
            logger.info(f"Created new session: {session_id}")
        
        if not session:
            logger.error(f"Session is None for session_id: {session_id}")
            raise HTTPException(
                status_code=500,
                detail="Session data unavailable. Please try again."
            )
        
        extract_request = SupplierExtractRequest(prompt=prompt)
        
        try:
            extract_response = await self.extract_service.extract_supplier_data(extract_request)
            logger.debug(f"Extracted {len(extract_response.extractedFields)} fields from prompt")
        except HTTPException as e:
            logger.error(f"Extraction error: {e.status_code} - {e.detail}")
            error_message = await self._generate_ai_error_message(str(e.detail), prompt)
            return SupplierChatResponse(
                success=False,
                sessionId=session_id,
                message=error_message,
                type="extraction_error",
                extractedData=None,
                missingFields=[],
                status="error"
            )
        
        existing_data = session.get("extracted_data", {}) if isinstance(session, dict) else {}
        
        new_data = {}
        if extract_response.payload:
            new_data = extract_response.payload.model_dump(exclude_none=True)
        
        merged_data = self._merge_data(existing_data, new_data)
        
        store = request.store or merged_data.get("store")
        
        missing_fields = self._check_required_fields(merged_data, store)
        
        update_success = await self.session_service.update_session(session_id, {
            "extracted_data": merged_data,
            "store": store
        })
        
        if not update_success:
            logger.warning(f"Failed to update session {session_id}, but continuing with response")
        
        payload = SupplierPayload(**merged_data)
        
        if missing_fields:
            logger.info(f"Missing fields: {missing_fields}")
            message = await self._generate_ai_response_message(missing_fields, merged_data, prompt)
            
            if "contact" in missing_fields:
                status = "waiting_for_contact"
            elif "name" in missing_fields:
                status = "waiting_for_name"
            elif "agency" in missing_fields:
                status = "waiting_for_agency"
            elif "store" in missing_fields:
                status = "waiting_for_store"
            else:
                status = "waiting_for_fields"
            
            return SupplierChatResponse(
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
            
            return SupplierChatResponse(
                success=True,
                sessionId=session_id,
                message=message,
                type="ready_to_create",
                extractedData=payload,
                missingFields=[],
                status="ready_to_create"
            )

