"""
Health Check Router
"""
from fastapi import APIRouter
from app.database.mongodb import get_database
from app.database.redis_client import get_redis

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint"""
    db_status = "connected"
    redis_status = "connected"
    
    try:
        db = get_database()
        await db.command('ping')
    except:
        db_status = "disconnected"
    
    try:
        redis = get_redis()
        if redis:
            await redis.ping()
        else:
            redis_status = "not_configured"
    except:
        redis_status = "disconnected"
    
    return {
        "status": "healthy" if db_status == "connected" else "unhealthy",
        "database": db_status,
        "redis": redis_status,
        "service": "DragBizz Voice AI"
    }
