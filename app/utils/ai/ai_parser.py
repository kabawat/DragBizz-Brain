from typing import Dict, Any
import json
import re
from fastapi import HTTPException


def _normalize_message_content(content: Any) -> str:
    """
    Normalize OpenAI/OpenRouter message content to plain text.
    Supports:
    - string content
    - list content e.g. [{"type":"text","text":"..."}, ...]
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                # Common: {"type":"text","text":"..."}
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
                    continue
                # Fallback keys sometimes used by adapters
                alt = item.get("content")
                if isinstance(alt, str) and alt:
                    parts.append(alt)
        return "".join(parts)
    return ""


def parse_text_response(ai_response: Dict[str, Any]) -> str:
    if not isinstance(ai_response, dict):
        raise ValueError("Invalid AI response format")
    
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
    
    content = _normalize_message_content(message.get("content"))
    if content:
        content = content.strip().replace("```", "").strip()
        if content:
            return content
    
    raise ValueError("Empty content in AI response")


def parse_json_response(ai_response: Dict[str, Any]) -> Dict[str, Any]:
    try:
        if not isinstance(ai_response, dict):
            raise ValueError("AI response is not a dictionary")
        
        choices = ai_response.get("choices", [])
        if not choices or not isinstance(choices, list):
            raise ValueError("No choices found in AI response")
        
        if not choices[0] or not isinstance(choices[0], dict):
            raise ValueError("Invalid choice format in AI response")
        
        message = choices[0].get("message", {})
        if not message or not isinstance(message, dict):
            raise ValueError("Invalid message format in AI response")
        
        content = _normalize_message_content(message.get("content"))
        if not content or not isinstance(content, str):
            raise ValueError("Empty or invalid content in AI response")
        
        json_str = re.sub(r'^```json\s*|^```\s*|\s*```$', '', content.strip())
        if not json_str:
            raise ValueError("Empty JSON string after cleaning")
        
        # Cleanup: Remove control characters except newline and tab
        json_str = "".join(char for char in json_str if ord(char) >= 32 or char in "\n\r\t")
        
        # Cleanup: Handle potential trailing commas (common AI mistake)
        json_str = re.sub(r',\s*([\]}])', r'\1', json_str)

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as decode_err:
            # Try to fix truncated JSON if it looks truncated (ends with a partial string or object)
            if "Unterminated string" in str(decode_err) or "Expecting" in str(decode_err):
                # Basic attempt to close JSON if truncated
                temp_json = json_str.strip()
                # If it ends with a comma, remove it
                if temp_json.endswith(','):
                    temp_json = temp_json[:-1]
                
                # Close open braces and brackets
                open_braces = temp_json.count('{') - temp_json.count('}')
                open_brackets = temp_json.count('[') - temp_json.count(']')
                
                # If it's inside an unterminated string, try to close it first
                if "Unterminated string" in str(decode_err):
                    temp_json += '"'
                
                temp_json += ']' * max(0, open_brackets)
                temp_json += '}' * max(0, open_braces)
                
                try:
                    parsed = json.loads(temp_json)
                except:
                    # Fallback to original error if healing fails
                    raise decode_err
            else:
                raise decode_err

        if not isinstance(parsed, dict):
            raise ValueError("Parsed JSON is not a dictionary")
        
        return parsed
        
    except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError) as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"JSON Parse Error: {str(e)} | Content snippet: {content[:200]}...", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse AI response: {str(e)}"
        )

