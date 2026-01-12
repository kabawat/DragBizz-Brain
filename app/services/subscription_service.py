from typing import Dict, Any, Optional
import logging
import httpx
from fastapi import HTTPException

from app.config.settings import get_settings
from app.services.http import HttpClient

logger = logging.getLogger(__name__)


class SubscriptionService:
    AI_SERVICE_FEATURE_KEY = "VOICE_AI"
    
    def __init__(self):
        self.settings = get_settings()
        self.http_client = HttpClient(timeout=10)
    
    async def check_feature_access(self, user_id: str, feature_key: str = None, token: Optional[str] = None) -> Dict[str, Any]:
        feature_key = feature_key or self.AI_SERVICE_FEATURE_KEY
        
        try:
            url = f"{self.settings.subscription_service_url}/usage/quota"
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            else:
                logger.warning(f"No token provided for feature access check for user {user_id}")
            params = {
                "userId": user_id,
                "featureKey": feature_key
            }
            
            try:
                response = await self.http_client.get(url, headers=headers, params=params)
                response_data = response.get("data", {}) if isinstance(response, dict) else {}
                quota = response_data.get("quota", {}) if isinstance(response_data, dict) else {}
                
                has_access = quota.get("hasAccess", False)
                
                if not has_access:
                    logger.warning(
                        f"Feature {feature_key} not available for user {user_id}"
                    )
                    
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "message": f"Voice AI feature is not available in your subscription plan. Please upgrade to use this feature.",
                            "quota": quota,
                            "feature_key": feature_key,
                            "error_type": "subscription_error"
                        }
                    )
                
                return {
                    "hasAccess": True,
                    "message": "Feature is available"
                }
                
            except HTTPException:
                raise
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code if e.response else 500
                try:
                    error_detail = e.response.json() if e.response else {}
                    message_obj = error_detail.get("message", {})
                    if isinstance(message_obj, dict):
                        error_message = message_obj.get("message", "Feature not available")
                    else:
                        error_message = message_obj if isinstance(message_obj, str) else "Feature not available"
                    
                    logger.warning(f"Feature access check failed {status_code}: {error_message}")
                    
                    raise HTTPException(
                        status_code=status_code,
                        detail={
                            "message": error_message,
                            "quota": {},
                            "feature_key": feature_key,
                            "error_type": "subscription_error"
                        }
                    )
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(
                        status_code=status_code,
                        detail={
                            "message": "Feature not available",
                            "quota": {},
                            "feature_key": feature_key,
                            "error_type": "subscription_error"
                        }
                    )
            except Exception as e:
                logger.error(f"Error checking feature access: {str(e)}", exc_info=True)
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": "Subscription service is temporarily unavailable. Please try again later.",
                        "error_type": "service_unavailable"
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in check_feature_access: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "message": "Error checking feature access",
                    "error_type": "internal_error"
                }
            )

