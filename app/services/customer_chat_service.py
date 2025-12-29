from typing import Any, Dict, Optional
import re
import logging

from fastapi import HTTPException

from app.config.settings import get_settings
from app.models.customer import CustomerChatRequest, CustomerChatResponse, CustomerExtractRequest, CustomerPayload
from app.services.customer_extract_service import CustomerExtractService
from app.services.session_service import SessionService
from app.services.http import HttpClient
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class CustomerChatService:
    """Service for conversational customer creation with session management."""
    
    BASE_URL = "https://openrouter.ai/api/v1"
    CHAT_ENDPOINT = "/chat/completions"
    DEFAULT_MODEL = "openai/gpt-4o-mini"
    FALLBACK_MODEL = "google/gemini-2.0-flash-exp:free"
    SECONDARY_FALLBACK = "meta-llama/llama-3.2-3b-instruct:free"
    DEFAULT_TEMPERATURE = 0.3
    DEFAULT_MAX_TOKENS = 150  # Reduced for cost savings (sufficient for brief responses)
    
    # Optimized prompt - reduced tokens for cost savings
    CONVERSATION_PROMPT_BASE = """Voice AI. Ask missing customer details. Same language. Brief (1-2 sentences). Text only."""
    
    def __init__(self):
        self.extract_service = CustomerExtractService()
        self.session_service = SessionService()
        self.settings = get_settings()
        self.http_client = HttpClient(timeout=self.settings.ai_request_timeout)
        self.subscription_service = SubscriptionService()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - no cleanup needed (using shared client)."""
        # Shared HTTP client is closed at application shutdown
        pass
    
    def _merge_data(self, existing: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        """Merge existing and new extracted data."""
        merged = existing.copy()
        
        # Merge simple fields (new overwrites existing if not null)
        for field in ["name", "phone", "email", "store"]:
            if new.get(field):
                merged[field] = new[field]
        
        # Merge company details
        if new.get("companyDetails"):
            if not merged.get("companyDetails"):
                merged["companyDetails"] = {}
            merged["companyDetails"].update(new["companyDetails"])
        
        # Merge addresses
        if new.get("addresses"):
            if not merged.get("addresses"):
                merged["addresses"] = {}
            for addr_type in ["billing", "shipping"]:
                if new["addresses"].get(addr_type):
                    if not merged["addresses"].get(addr_type):
                        merged["addresses"][addr_type] = {}
                    merged["addresses"][addr_type].update(new["addresses"][addr_type])
        
        return merged
    
    def _is_valid_object_id(self, value: str) -> bool:
        """Check if string is a valid MongoDB ObjectId format (24 hex characters)."""
        if not value or not isinstance(value, str):
            return False
        return bool(re.match(r'^[0-9a-fA-F]{24}$', value.strip()))
    
    def _check_required_fields(self, data: Dict[str, Any], store: Optional[str]) -> list[str]:
        """Check for missing required fields only (as per customer API validation)."""
        missing = []
        
        # Required: name (2-100 chars)
        if not data.get("name") or len(str(data.get("name", "")).strip()) < 2:
            missing.append("name")
        
        # Required: phone OR email (at least one)
        if not data.get("phone") and not data.get("email"):
            missing.append("contact")
        
        # Required: store (valid ObjectId)
        store_value = store or data.get("store")
        if not store_value:
            missing.append("store")
        elif not self._is_valid_object_id(store_value):
            # Store ID provided but invalid format
            missing.append("store")
            logger.warning(f"Invalid store ID format: {store_value}")
        
        # Note: companyDetails, addresses are optional - not checked
        return missing
    
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
    
    def _detect_language(self, text: str) -> str:
        """Detect if text contains non-English characters. Returns 'mixed' if non-English detected, else 'english'.
        Actual language detection is handled by AI - this is just a hint for fallback messages."""
        if not text or not isinstance(text, str):
            return "english"
        
        text = text.strip()
        if len(text) < 2:
            return "english"  # Too short to detect
        
        # Check if text contains non-ASCII characters (indicating non-English)
        has_non_ascii = any(ord(char) > 127 for char in text)
        
        if has_non_ascii:
            return "mixed"  # Contains non-English characters - AI will handle exact language
        else:
            return "english"
    
    def _get_conversation_prompt(self, user_language: str) -> str:
        """Get conversation prompt - AI will automatically detect and respond in user's language."""
        base = self.CONVERSATION_PROMPT_BASE
        
        # Universal instruction - AI will detect language from user query
        instruction = "CRITICAL: Always respond in the EXACT same language, script, and style as the user's query. Match the user's language perfectly - if they write in Hindi, respond in Hindi; if Gujarati, respond in Gujarati; if English, respond in English. Use the same script (Devanagari, Gujarati, Tamil, etc.) as the user."
        
        return base + " " + instruction
    
    async def _get_fallback_message(self, missing_fields: list[str], user_prompt: str, user_id: Optional[str] = None) -> str:
        """Generate fallback message using AI in user's language when primary AI call fails."""
        # Try to generate message using AI in user's language
        try:
            user_language_hint = self._detect_language(user_prompt)
            conversation_prompt = self._get_conversation_prompt(user_language_hint)
            
            # Build message request
            missing_str = ", ".join(missing_fields)
            ai_user_prompt = f"User asked: \"{user_prompt[:100]}\". Missing fields: {missing_str}. Ask user to provide missing information. Respond in EXACT same language and script as user's query: \"{user_prompt[:50]}\""
            
            messages = [
                {"role": "system", "content": conversation_prompt},
                {"role": "user", "content": ai_user_prompt}
            ]
            
            content = await self._call_ai_api(messages, use_cache=False, user_id=user_id)  # Don't cache fallback messages
            if content:
                return content
        except Exception as e:
            logger.warning(f"Failed to generate AI fallback message: {str(e)}")
        
        # Ultimate fallback - simple English message (should rarely be used)
        if "contact" in missing_fields:
            return "Please provide customer email ID or phone number"
        elif "name" in missing_fields:
            return "Please provide customer name"
        elif "store" in missing_fields:
            return "Please provide store ID"
        else:
            return "Some required information is missing, please provide"
    
    async def _get_fallback_success_message(self, user_prompt: str, user_id: Optional[str] = None) -> str:
        """Generate success fallback message using AI in user's language."""
        # Try to generate message using AI in user's language
        try:
            user_language_hint = self._detect_language(user_prompt)
            conversation_prompt = self._get_conversation_prompt(user_language_hint)
            
            ai_user_prompt = f"User asked: \"{user_prompt[:100]}\". All required customer details are now available. Confirm this to the user. Respond in EXACT same language and script as user's query: \"{user_prompt[:50]}\""
            
            messages = [
                {"role": "system", "content": conversation_prompt},
                {"role": "user", "content": ai_user_prompt}
            ]
            
            content = await self._call_ai_api(messages, use_cache=False, user_id=user_id)  # Don't cache fallback messages
            if content:
                return content
        except Exception as e:
            logger.warning(f"Failed to generate AI success fallback message: {str(e)}")
        
        # Ultimate fallback - simple English message
        return "All required details are available. Ready to create customer."
    
    async def _get_fallback_error_message(self, user_prompt: str, error_detail: str = "", user_id: Optional[str] = None) -> str:
        """Generate error fallback message using AI in user's language."""
        # Try to generate message using AI in user's language
        try:
            user_language_hint = self._detect_language(user_prompt)
            conversation_prompt = self._get_conversation_prompt(user_language_hint)
            
            error_text = f"Error: {error_detail}" if error_detail else "An error occurred"
            ai_user_prompt = f"User asked: \"{user_prompt[:100]}\". {error_text}. Ask user to try again or provide information differently. Respond in EXACT same language and script as user's query: \"{user_prompt[:50]}\""
            
            messages = [
                {"role": "system", "content": conversation_prompt},
                {"role": "user", "content": ai_user_prompt}
            ]
            
            content = await self._call_ai_api(messages, use_cache=False, user_id=user_id)  # Don't cache fallback messages
            if content:
                return content
        except Exception as e:
            logger.warning(f"Failed to generate AI error fallback message: {str(e)}")
        
        # Ultimate fallback - simple English message
        return "An error occurred. Please try your request again or provide information in a different way."
    
    async def _parse_ai_response(self, ai_response: Dict[str, Any]) -> str:
        """Parse AI response and extract content. Returns content or raises ValueError."""
        if not isinstance(ai_response, dict):
            raise ValueError("Invalid AI response format")
        
        # Check for errors in response
        if "error" in ai_response:
            error_msg = ai_response.get("error", {})
            if isinstance(error_msg, dict):
                error_detail = error_msg.get("message", str(error_msg))
            else:
                error_detail = str(error_msg)
            raise ValueError(f"AI API error: {error_detail}")
        
        choices = ai_response.get("choices", [])
        if not choices or not isinstance(choices, list):
            raise ValueError("No choices in AI response")
        
        message = choices[0].get("message", {})
        if not isinstance(message, dict):
            raise ValueError("Invalid message format in AI response")
        
        content = message.get("content", "")
        if content and isinstance(content, str):
            content = content.strip().replace("```", "").strip()
            if content:
                return content
        
        # If we get here, content was empty
        raise ValueError("Empty content in AI response")
    
    async def _call_ai_api(self, messages: list[Dict[str, str]], use_cache: bool = True, user_id: Optional[str] = None) -> Optional[str]:
        """
        Call AI API with fallback models. Returns content or None if all models fail.
        
        Args:
            messages: AI conversation messages
            use_cache: Whether to use cache
            user_id: User ID for subscription limit checking
        """
        # Check subscription limits before making AI API call
        if user_id and self.settings.subscription_enabled:
            try:
                await self.subscription_service.check_usage(user_id=user_id, quantity=1)
            except HTTPException:
                # Re-raise HTTP exceptions (limit exceeded)
                raise
            except Exception as e:
                # Log but continue if subscription service fails (fail-open)
                logger.warning(f"Subscription check failed, allowing request: {str(e)}")
        
        models_to_try = [self.DEFAULT_MODEL, self.FALLBACK_MODEL, self.SECONDARY_FALLBACK]
        last_error = None
        successful_model = None
        
        for model in models_to_try:
            try:
                request_data = {
                    "model": model,
                    "messages": messages,
                    "temperature": self.DEFAULT_TEMPERATURE,
                    "max_tokens": self.DEFAULT_MAX_TOKENS
                }
                
                logger.debug(f"Calling AI API with model: {model}")
                ai_response = await self.http_client.post(
                    url=f"{self.BASE_URL}{self.CHAT_ENDPOINT}",
                    headers=self._build_headers(),
                    json=request_data,
                    use_cache=use_cache
                )
                
                content = await self._parse_ai_response(ai_response)
                logger.debug(f"AI API success with model: {model}")
                successful_model = model
                break  # Success, exit loop
                
            except HTTPException as e:
                last_error = e
                logger.warning(f"AI API HTTP error with model {model}: {e.status_code} - {e.detail}")
                if e.status_code == 429 and model != models_to_try[-1]:
                    continue
                break
            except (ValueError, KeyError, TypeError) as e:
                last_error = e
                logger.warning(f"AI API parsing error with model {model}: {str(e)}")
                if model == models_to_try[-1]:
                    break
                continue
        
        # Increment usage after successful AI call
        if successful_model and user_id and self.settings.subscription_enabled:
            try:
                metadata = {
                    "model": successful_model,
                    "tokens": self.DEFAULT_MAX_TOKENS,
                    "cache_used": use_cache
                }
                await self.subscription_service.increment_usage(
                    user_id=user_id,
                    quantity=1,
                    metadata=metadata
                )
            except Exception as e:
                # Log but don't fail the request
                logger.warning(f"Failed to increment usage: {str(e)}")
        
        if last_error and not successful_model:
            logger.error(f"All AI models failed. Last error: {last_error}")
            return None
        
        # Return content if we have it, otherwise None
        return content if successful_model else None
    
    async def _generate_ai_response_message(self, missing_fields: list[str], extracted_data: Dict[str, Any], user_prompt: str, user_id: Optional[str] = None) -> str:
        """Generate conversational response using AI for missing fields in user's language."""
        # Detect user's language hint (just for prompt, AI will detect exact language)
        user_language_hint = self._detect_language(user_prompt)
        conversation_prompt = self._get_conversation_prompt(user_language_hint)
        
        # Build compact context - only required fields (optimized for tokens)
        missing = []
        if "name" in missing_fields:
            missing.append("name")
        if "contact" in missing_fields:
            missing.append("contact")
        if "store" in missing_fields:
            missing.append("store")
        
        # Show only required fields that we have
        have = []
        if extracted_data.get("name"):
            have.append(f"name:{extracted_data['name']}")
        if extracted_data.get("phone"):
            have.append("phone")
        elif extracted_data.get("email"):
            have.append("email")
        
        # Compact user prompt (reduced tokens) - explicitly instruct to use same language
        ai_user_prompt = f"Missing:{','.join(missing)}. Have:{','.join(have) if have else 'none'}. User query: \"{user_prompt[:80]}\". IMPORTANT: Respond in the EXACT same language and script as the user's query. Use the same language as: \"{user_prompt[:50]}\""
        
        messages = [
            {"role": "system", "content": conversation_prompt},
            {"role": "user", "content": ai_user_prompt}
        ]
        
        content = await self._call_ai_api(messages, use_cache=True, user_id=user_id)
        if content:
            return content
        
        # Fallback to AI-generated message in user's language if primary AI fails
        return await self._get_fallback_message(missing_fields, user_prompt, user_id)
    
    async def _generate_ai_success_message(self, extracted_data: Dict[str, Any], user_prompt: str, user_id: Optional[str] = None) -> str:
        """Generate success message using AI when all fields are ready in user's language."""
        # Detect user's language hint (just for prompt, AI will detect exact language)
        user_language_hint = self._detect_language(user_prompt)
        conversation_prompt = self._get_conversation_prompt(user_language_hint)
        
        name = extracted_data.get('name', 'N/A')
        contact = extracted_data.get('email') or extracted_data.get('phone', 'N/A')
        # Optimized prompt (reduced tokens) - explicitly instruct to use same language
        ai_user_prompt = f"Ready. Name:{name}, Contact:{contact}. User query: \"{user_prompt[:80]}\". IMPORTANT: Respond in the EXACT same language and script as the user's query. Use the same language as: \"{user_prompt[:50]}\""
        
        messages = [
            {"role": "system", "content": conversation_prompt},
            {"role": "user", "content": ai_user_prompt}
        ]
        
        content = await self._call_ai_api(messages, use_cache=True, user_id=user_id)
        if content:
            return content
        
        # Fallback to AI-generated message in user's language if primary AI fails
        return await self._get_fallback_success_message(user_prompt, user_id)
    
    async def _generate_ai_error_message(self, error_detail: str, user_prompt: str, user_id: Optional[str] = None) -> str:
        """Generate user-friendly error message using AI in user's language."""
        # Detect user's language hint (just for prompt, AI will detect exact language)
        user_language_hint = self._detect_language(user_prompt)
        conversation_prompt = self._get_conversation_prompt(user_language_hint)
        
        # Optimized prompt (reduced tokens) - explicitly instruct to use same language
        ai_user_message = f"Error occurred. User query: \"{user_prompt[:80]}\". Error: {error_detail[:80]}. IMPORTANT: Respond in the EXACT same language and script as the user's query. Ask user to retry. Use the same language as: \"{user_prompt[:50]}\""
        
        messages = [
            {"role": "system", "content": conversation_prompt},
            {"role": "user", "content": ai_user_message}
        ]
        
        content = await self._call_ai_api(messages, use_cache=True, user_id=user_id)
        if content:
            return content
        
        # Fallback to AI-generated message in user's language if primary AI fails
        return await self._get_fallback_error_message(user_prompt, error_detail, user_id)
    
    async def handle_conversation(self, request: CustomerChatRequest, user_id: Optional[str] = None) -> CustomerChatResponse:
        """Handle conversational customer creation."""
        # Validate input prompt
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
        
        # Get or create session
        session_id = request.sessionId
        session = None
        
        if session_id:
            session = self.session_service.get_session(session_id)
            if not session:
                # Session expired, create new one
                logger.info(f"Session {session_id} expired, creating new session")
                session_id = None
        
        if not session_id:
            # Create new session
            session_id = self.session_service.create_session()
            session = self.session_service.get_session(session_id)
            logger.info(f"Created new session: {session_id}")
        
        # Extract data from current prompt
        extract_request = CustomerExtractRequest(prompt=prompt)
        
        try:
            extract_response = await self.extract_service.extract_customer_data(extract_request)
            logger.debug(f"Extracted {len(extract_response.extractedFields)} fields from prompt")
        except HTTPException as e:
            logger.error(f"Extraction error: {e.status_code} - {e.detail}")
            error_message = await self._generate_ai_error_message(str(e.detail), prompt, user_id)
            return CustomerChatResponse(
                success=False,
                sessionId=session_id,
                message=error_message,
                type="extraction_error",
                extractedData=None,
                missingFields=[],
                status="error"
            )
        
        # Get existing extracted data
        existing_data = session.get("extracted_data", {})
        
        # Convert CustomerPayload to dict for merging
        new_data = {}
        if extract_response.payload:
            new_data = extract_response.payload.model_dump(exclude_none=True)
        
        # Merge with existing data
        merged_data = self._merge_data(existing_data, new_data)
        
        # Use store from request if provided, otherwise from merged data
        store = request.store or merged_data.get("store")
        
        # Check required fields
        missing_fields = self._check_required_fields(merged_data, store)
        
        # Update session with merged data
        self.session_service.update_session(session_id, {
            "extracted_data": merged_data,
            "store": store
        })
        
        # Convert merged data to CustomerPayload
        payload = CustomerPayload(**merged_data)
        
        # Generate response based on missing fields
        if missing_fields:
            logger.info(f"Missing fields: {missing_fields}")
            message = await self._generate_ai_response_message(missing_fields, merged_data, prompt, user_id)
            
            # Determine status
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
            message = await self._generate_ai_success_message(merged_data, prompt, user_id)
            
            return CustomerChatResponse(
                success=True,
                sessionId=session_id,
                message=message,
                type="ready_to_create",
                extractedData=payload,
                missingFields=[],
                status="ready_to_create"
            )
