import logging
from fastapi import Request, HTTPException

from app.services.subscription_service import SubscriptionService
from app.services.cache.cache_service import get_cache, set_cache
from app.constants.status_code import STATUS_CODES
from app.utils.responseHandler.standardized import parse_error_for_response

logger = logging.getLogger(__name__)

AI_FEATURE_CACHE_TTL = 600
CACHE_KEY_PREFIX = "ai_feature_access:"
CACHE_KEY_VERSION = "v2"  # Bump to invalidate stale cache after auth/subscription fixes


def _get_cache_key(user_id: str) -> str:
    return f"{CACHE_KEY_PREFIX}{user_id}:{CACHE_KEY_VERSION}"


async def check_ai_feature_access(request: Request) -> dict:
    try:
        user = getattr(request.state, 'user', None)
        user_id = user.get('sub') or user.get('id') if user else None
        token = getattr(request.state, 'token', None)
        
        if not user_id:
            raise HTTPException(
                status_code=STATUS_CODES["UNAUTHORIZED"],
                detail={
                    "status": False,
                    "message": "User ID not found. Please ensure authentication middleware runs before this.",
                    "error": "Unauthorized"
                }
            )
        
        cache_key = _get_cache_key(user_id)
        cached_access = await get_cache(cache_key)
        
        if cached_access is not None:
            has_access = cached_access.get("hasAccess", False)
            logger.debug(f"AI feature access cache hit for user {user_id}: {has_access}")
            
            if not has_access:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "status": False,
                        "message": "Voice AI feature is not available in your subscription plan. Please upgrade to use this feature.",
                        "error": "Feature not available",
                        "data": {
                            "quota": cached_access.get("quota", {}),
                            "feature_key": "VOICE_AI"
                        }
                    }
                )
            
            return user
        
        logger.debug(f"AI feature access cache miss for user {user_id}, checking subscription service")
        
        subscription_service = SubscriptionService()
        
        try:
            access_result = await subscription_service.check_feature_access(
                user_id=user_id,
                feature_key="VOICE_AI",
                token=token
            )
            
            quota_info = {
                "hasAccess": access_result.get("hasAccess", True),
                "remaining": -1,
                "limit": -1,
                "usageType": "UNLIMITED"
            }
            
            cache_data = {
                "hasAccess": access_result.get("hasAccess", True),
                "quota": quota_info,
                "checkedAt": None
            }
            
            await set_cache(cache_key, cache_data, AI_FEATURE_CACHE_TTL)
            logger.debug(f"Cached AI feature access for user {user_id}: {cache_data['hasAccess']}")
            
            return user
            
        except HTTPException as e:
            # Only cache 403 (no access) - don't cache 400/5xx (auth bugs or service errors)
            if e.status_code == 403:
                cache_data = {
                    "hasAccess": False,
                    "quota": e.detail.get("quota", {}) if isinstance(e.detail, dict) else {},
                    "error": e.detail.get("message", "Feature not available") if isinstance(e.detail, dict) else str(e.detail)
                }
                await set_cache(cache_key, cache_data, 300)
            # 400, 503 etc: don't cache - allow retry (avoids stale cache after fixes)

            error_detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
            raise HTTPException(
                status_code=e.status_code,
                detail={
                    "status": False,
                    "message": error_detail.get("message", "Voice AI feature is not available in your subscription plan."),
                    "error": "Feature not available",
                    "data": {
                        "quota": error_detail.get("quota", {}),
                        "feature_key": "VOICE_AI"
                    }
                }
            )
        except Exception as e:
            logger.error(f"Subscription service error: {str(e)}", exc_info=True)
            # Don't cache service errors - allow retry on next request (avoids stale cache blocking after fix)
            raise HTTPException(
                status_code=503,
                detail={
                    "status": False,
                    "message": "Subscription service is temporarily unavailable. Please try again later.",
                    "error": "Service unavailable"
                }
            )
            
    except HTTPException:
        raise
    except Exception as err:
        logger.error(f"Error in AI feature middleware: {str(err)}", exc_info=True)
        error_data = parse_error_for_response(err)
        raise HTTPException(
            status_code=error_data.get("status_code", STATUS_CODES["INTERNAL_SERVER_ERROR"]),
            detail={
                "status": False,
                "message": error_data.get("message", "Error checking AI feature access"),
                "error": "Internal error"
            }
        )

