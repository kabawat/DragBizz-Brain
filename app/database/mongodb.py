"""
MongoDB Database Connection
"""
from motor.motor_asyncio import AsyncIOMotorClient
from app.config.settings import settings
from app.utils.logger import logger

# Global MongoDB client
client: AsyncIOMotorClient = None
database = None


async def init_db():
    """Initialize MongoDB connection"""
    global client, database
    
    try:
        client = AsyncIOMotorClient(
            settings.MONGODB_URI,
            maxPoolSize=50,
            minPoolSize=10,
            serverSelectionTimeoutMS=5000
        )
        
        # Test connection
        await client.admin.command('ping')
        
        database = client[settings.MONGODB_DB_NAME]
        
        logger.info("✅ MongoDB connected successfully")
        
        # Create indexes
        await create_indexes()
        
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {str(e)}")
        raise


async def close_db():
    """Close MongoDB connection"""
    global client
    
    if client:
        client.close()
        logger.info("✅ MongoDB connection closed")


async def create_indexes():
    """Create database indexes"""
    try:
        # Voice Commands indexes
        voice_commands = database.voice_commands
        await voice_commands.create_index([("userId", 1), ("createdAt", -1)])
        await voice_commands.create_index([("storeId", 1), ("createdAt", -1)])
        await voice_commands.create_index("sessionId")
        await voice_commands.create_index("status")
        await voice_commands.create_index([("userId", 1), ("status", 1)])
        
        # Voice Sessions indexes
        voice_sessions = database.voice_sessions
        await voice_sessions.create_index("sessionId", unique=True)
        await voice_sessions.create_index([("userId", 1), ("status", 1)])
        await voice_sessions.create_index("expiresAt")
        
        # Voice Intent Templates indexes
        voice_intent_templates = database.voice_intent_templates
        await voice_intent_templates.create_index([("intent", 1), ("language", 1)])
        
        logger.info("✅ Database indexes created")
        
    except Exception as e:
        logger.warning(f"⚠️ Index creation warning: {str(e)}")


def get_database():
    """Get database instance"""
    return database
