import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import logging
from bson.objectid import ObjectId
from bson.errors import InvalidId

# Configure logging
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# MongoDB configuration
MONGODB_URL = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = "interviews"

# Initialize MongoDB client
try:
    client = AsyncIOMotorClient(MONGODB_URL, serverSelectionTimeoutMS=5000)
    db = client[DATABASE_NAME]
    candidates_collection = db.candidates
    logger.info(f"✅ Connected to MongoDB database: {DATABASE_NAME}")
except Exception as e:
    logger.error(f"❌ Failed to initialize MongoDB connection: {e}")
    raise

async def test_connection():
    """Test database connection"""
    try:
        await client.admin.command('ping')
        logger.info("✅ Database connection test successful")
        return True
    except Exception as e:
        logger.error(f"❌ Database connection test failed: {e}")
        return False

async def update_candidate_status(candidate_id, status, extra_fields=None):
    """Update candidate status with async support"""
    try:
        update_data = {"status": status}
        if extra_fields:
            update_data.update(extra_fields)
            
        result = await candidates_collection.update_one(
            {"_id": candidate_id},
            {"$set": update_data}
        )
        
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"❌ Error updating candidate status: {e}")
        raise

async def get_interview_result(interview_id):
    """Fetch interview result from the database by interview ID."""
    try:
        # Convert the interview_id to ObjectId
        interview_object_id = ObjectId(interview_id)
    except InvalidId:
        logger.error(f"❌ Invalid interview_id: {interview_id}")
        return {"error": "Invalid interview ID format"}

    try:
        result = await candidates_collection.find_one({"_id": interview_object_id})
        if result:
            return {
                "status": result.get("status", "Unknown"),
                "score": result.get("score", "N/A"),
                "category": result.get("category", "N/A"),
            }
        else:
            return {"error": "Interview result not found"}
    except Exception as e:
        logger.error(f"❌ Error fetching interview result: {e}")
        return {"error": "An error occurred while fetching the interview result"}