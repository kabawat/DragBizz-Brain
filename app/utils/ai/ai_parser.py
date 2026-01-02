from typing import Dict, Any
import json
import re
from fastapi import HTTPException


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
    
    content = message.get("content", "")
    if content and isinstance(content, str):
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
        
        content = message.get("content", "")
        if not content or not isinstance(content, str):
            raise ValueError("Empty or invalid content in AI response")
        
        json_str = re.sub(r'^```json\s*|^```\s*|\s*```$', '', content.strip())
        if not json_str:
            raise ValueError("Empty JSON string after cleaning")
        
        parsed = json.loads(json_str)
        if not isinstance(parsed, dict):
            raise ValueError("Parsed JSON is not a dictionary")
        
        return parsed
        
    except (json.JSONDecodeError, KeyError, IndexError, ValueError, TypeError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse AI response: {str(e)}"
        )

