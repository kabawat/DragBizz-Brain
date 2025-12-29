from typing import Dict, Any, Optional
from urllib.parse import urlparse
import hashlib
import json

import jwt
from jwt import PyJWKClient

from app.config.settings import get_settings
from app.services.cache import get_cache, set_cache


_settings = get_settings()
jwks_url = f"{_settings.auth_url}/.well-known/jwks.json"
parsed = urlparse(jwks_url)
hostname = (parsed.hostname or "").lower()
dev_indicators = ["localhost", "127.0.0.1", "0.0.0.0", ""]
is_development = any(indicator in hostname for indicator in dev_indicators) or not hostname or _settings.debug
is_production_domain = "." in hostname and hostname and not is_development
if is_production_domain and not jwks_url.startswith("https://"):
    raise ValueError("JWKS URL must use HTTPS in production")

JWKS_CLIENT = PyJWKClient(jwks_url)

VERIFY_CACHE_TTL = 300
VERIFY_CACHE_PREFIX = "verify:token:"


def get_token_cache_key(token: str) -> str:
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return f"{VERIFY_CACHE_PREFIX}{token_hash}:voice-ai"


def extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
    if not auth_header or not isinstance(auth_header, str):
        return None
    
    parts = auth_header.split()
    return parts[1] if len(parts) == 2 and parts[0] == "Bearer" else None


async def verify_access_token(token: str) -> Dict[str, Any]:
    settings = get_settings()
    
    try:
        # Step 1: Check Redis cache first (ultra fast - ~1ms)
        cache_key = get_token_cache_key(token)
        cached_result = get_cache(cache_key)
        
        if cached_result:
            # Cache hit - return immediately
            return {
                "valid": cached_result["valid"],
                "expired": cached_result.get("expired", False),
                "decoded": cached_result.get("decoded"),
                "cached": True
            }

        # Step 2: Cache miss - verify via JWKS
        signing_key = JWKS_CLIENT.get_signing_key_from_jwt(token)
        
        # Support both single audience string and list of audiences
        audience = settings.jwt_audience
        if isinstance(audience, str):
            audience = [audience]
        
        # Decode token without audience check first, then manually validate audience
        # This allows us to handle tokens with multiple audiences more flexibly
        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[settings.jwt_algorithm],
                issuer=settings.jwt_issuer,
                options={"verify_exp": True, "verify_aud": False}  # Disable automatic audience check
            )
            
            # Manually validate audience
            token_aud = payload.get("aud", [])
            if isinstance(token_aud, str):
                token_aud = [token_aud]
            
            # Check if token has any of the required audiences
            has_valid_audience = any(aud in token_aud for aud in audience)
            
            if not has_valid_audience:
                return {
                    "valid": False,
                    "expired": False,
                    "decoded": None,
                    "error": f"Token audience {token_aud} does not match required {audience}",
                    "cached": False
                }
            
        except jwt.ExpiredSignatureError:
            raise  # Re-raise to be caught by outer handler
        except Exception as decode_err:
            return {
                "valid": False,
                "expired": False,
                "decoded": None,
                "error": f"Token decode error: {str(decode_err)}",
                "cached": False
            }

        # Step 3: Cache successful verification
        result = {
            "valid": True,
            "expired": False,
            "decoded": payload,
            "cached": False
        }

        # Cache for 5 minutes (less than token expiry)
        set_cache(cache_key, result, VERIFY_CACHE_TTL)

        return result
        
    except jwt.ExpiredSignatureError:
        # Handle expired tokens
        return {
            "valid": False,
            "expired": True,
            "decoded": None,
            "cached": False
        }
        
    except Exception as err:
        # Don't cache invalid tokens
        return {
            "valid": False,
            "expired": False,
            "decoded": None,
            "error": str(err),
            "cached": False
        }

