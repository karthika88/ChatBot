from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
import pytz
from bson import ObjectId
from app.database import candidates_collection
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/api/available-slots/{candidate_id}")
async def get_available_slots(candidate_id: str):
    try:
        # Verify candidate exists and is awaiting scheduling
        candidate = await candidates_collection.find_one({
            "_id": ObjectId(candidate_id),
            "status": "Awaiting Scheduling"
        })
        
        if not candidate:
            raise HTTPException(status_code=404, detail="No eligible candidate found")

        # Generate available slots
        slots = []
        current = datetime.now()
        end_date = current + timedelta(days=7)
        
        while current < end_date:
            if current.weekday() < 5:  # Monday-Friday
                for hour in range(9, 17):  # 9 AM to 5 PM
                    slot_time = current.replace(hour=hour, minute=0, second=0, microsecond=0)
                    if slot_time > datetime.now():
                        slots.append({
                            "datetime": slot_time.isoformat(),
                            "formatted": slot_time.strftime("%B %d, %Y %I:%M %p")
                        })
            current = current.replace(hour=0, minute=0) + timedelta(days=1)

        logger.info(f"Generated {len(slots)} available slots for candidate {candidate_id}")
        return {"available_slots": slots}
        
    except Exception as e:
        logger.error(f"Error getting available slots: {e}")
        raise HTTPException(status_code=500, detail=str(e))