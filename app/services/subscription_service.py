"""Subscription service client for checking usage limits."""
from typing import Dict, Any, Optional
import logging
import httpx
from fastapi import HTTPException

from app.config.settings import get_settings
from app.services.http import HttpClient

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Service for checking subscription limits and usage."""
    
    # Feature key for AI service
    AI_SERVICE_FEATURE_KEY = "VOICE_AI"
    
    def __init__(self):
        self.settings = get_settings()
        self.http_client = HttpClient(timeout=10)
        # Subscription service URL is now a property that constructs URL from base_url
    
    async def check_usage(self, user_id: str, feature_key: str = None, quantity: int = 1) -> Dict[str, Any]:
        """
        Check if user has usage quota for a feature.
        
        Args:
            user_id: User ID from JWT token
            feature_key: Feature key (defaults to VOICE_AI)
            quantity: Number of units to check (default 1)
        
        Returns:
            Dict with 'allowed', 'reason', and 'quota' information
        
        Raises:
            HTTPException: If limit exceeded or service unavailable
        """
        feature_key = feature_key or self.AI_SERVICE_FEATURE_KEY
        
        try:
            # Try HTTP API first (if subscription service exposes HTTP endpoints)
            url = f"{self.settings.subscription_service_url}/api/v1/usage/check"
            headers = {"Content-Type": "application/json"}
            payload = {
                "user_id": user_id,
                "feature_key": feature_key,
                "quantity": quantity
            }
            
            try:
                response = await self.http_client.post(url, headers=headers, json=payload, use_cache=False)
                
                if not response.get("allowed", False):
                    reason = response.get("reason", "Usage limit exceeded")
                    quota = response.get("quota", {})
                    
                    logger.warning(
                        f"Usage limit exceeded for user {user_id}, feature {feature_key}. "
                        f"Reason: {reason}, Quota: {quota}"
                    )
                    
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "message": reason,
                            "quota": quota,
                            "feature_key": feature_key
                        }
                    )
                
                return {
                    "allowed": True,
                    "reason": response.get("reason", ""),
                    "quota": response.get("quota", {})
                }
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error checking usage via HTTP: {str(e)}")
                # If HTTP fails, allow request (fail open for availability)
                # In production, you might want to fail closed
                logger.warning("Subscription service unavailable, allowing request (fail-open mode)")
                return {
                    "allowed": True,
                    "reason": "Subscription service unavailable",
                    "quota": {}
                }
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Unexpected error in check_usage: {str(e)}")
            # Fail open - allow request if subscription service is down
            return {
                "allowed": True,
                "reason": "Subscription service error",
                "quota": {}
            }
    
    async def increment_usage(self, user_id: str, feature_key: str = None, quantity: int = 1, metadata: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Increment usage counter for a feature after successful AI call.
        
        Args:
            user_id: User ID from JWT token
            feature_key: Feature key (defaults to VOICE_AI)
            quantity: Number of units used (default 1)
            metadata: Additional metadata (model used, tokens, etc.)
        
        Returns:
            Dict with 'success' and updated 'quota' information
        """
        feature_key = feature_key or self.AI_SERVICE_FEATURE_KEY
        
        try:
            url = f"{self.settings.subscription_service_url}/api/v1/usage/increment"
            headers = {"Content-Type": "application/json"}
            payload = {
                "user_id": user_id,
                "feature_key": feature_key,
                "quantity": quantity,
                "metadata": metadata or {}
            }
            
            try:
                response = await self.http_client.post(url, headers=headers, json=payload, use_cache=False)
                logger.debug(f"Incremented usage for user {user_id}, feature {feature_key}, quantity {quantity}")
                return {
                    "success": response.get("success", False),
                    "quota": response.get("quota", {})
                }
            except Exception as e:
                # Log error but don't fail the request
                logger.warning(f"Failed to increment usage: {str(e)}")
                return {
                    "success": False,
                    "quota": {}
                }
                
        except Exception as e:
            logger.error(f"Unexpected error in increment_usage: {str(e)}")
            return {
                "success": False,
                "quota": {}
            }
    
    async def get_quota(self, user_id: str, feature_key: str = None) -> Dict[str, Any]:
        """
        Get current quota information for a feature.
        
        Args:
            user_id: User ID from JWT token
            feature_key: Feature key (defaults to VOICE_AI)
        
        Returns:
            Dict with quota information (remaining, limit, usage_type, etc.)
        """
        feature_key = feature_key or self.AI_SERVICE_FEATURE_KEY
        
        try:
            url = f"{self.settings.subscription_service_url}/api/v1/usage/quota"
            headers = {"Content-Type": "application/json"}
            payload = {
                "user_id": user_id,
                "feature_key": feature_key
            }
            
            try:
                response = await self.http_client.post(url, headers=headers, json=payload, use_cache=True)
                return {
                    "success": response.get("success", False),
                    "quota": response.get("quota", {})
                }
            except Exception as e:
                logger.warning(f"Failed to get quota: {str(e)}")
                return {
                    "success": False,
                    "quota": {}
                }
                
        except Exception as e:
            logger.error(f"Unexpected error in get_quota: {str(e)}")
            return {
                "success": False,
                "quota": {}
            }

