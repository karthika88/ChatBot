from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta, timezone
from bson import ObjectId
from app.database import candidates_collection
from app.google_calendar import schedule_interview_event
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

@router.get("/available-slots/{candidate_id}")
async def get_available_slots(candidate_id: str):
    try:
        # Validate ObjectId
        if not ObjectId.is_valid(candidate_id):
            raise HTTPException(status_code=400, detail="Invalid candidate ID format")

        # Check if candidate exists and is eligible
        candidate = await candidates_collection.find_one({
            "_id": ObjectId(candidate_id),
            "status": "Awaiting Scheduling"
        })

        if not candidate:
            logger.error(f"Candidate not found or not eligible: {candidate_id}")
            raise HTTPException(status_code=404, detail="Candidate not found or not eligible for scheduling")

        # Generate available slots: every 30 minutes, 24/7, next 7 days
        slots = []
        current = datetime.utcnow().replace(second=0, microsecond=0)
        end_date = current + timedelta(days=7)

        while current < end_date:
            if current > datetime.utcnow():  # Skip past times
                slot_time = current
                slots.append({
                    "datetime": slot_time.isoformat() + 'Z',
                    "formatted": slot_time.strftime("%Y-%m-%d %I:%M %p UTC")
                })
            current += timedelta(minutes=30)

        logger.info(f"Generated {len(slots)} slots for candidate {candidate_id}")
        return {"available_slots": slots}

    except Exception as e:
        logger.error(f"Error getting available slots: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/schedule-interview")
async def schedule_interview(data: dict):
    try:
        candidate_id = data.get('candidate_id')
        interview_time = data.get('interview_time')
        
        logger.info(f"Received request to schedule interview for candidate_id={candidate_id} at {interview_time}")
        if not candidate_id or not interview_time:
            logger.error("Missing candidate_id or interview_time")
            raise HTTPException(status_code=400, detail="Missing required data")

        # Validate candidate exists
        candidate = await candidates_collection.find_one({"_id": ObjectId(candidate_id)})
        if not candidate:
            logger.error(f"Candidate not found in DB: {candidate_id}")
            raise HTTPException(status_code=404, detail="Candidate not found")


        try:
            logger.info(f"Scheduling interview for {candidate_id} at {interview_time}")
            event = await schedule_interview_event(
                candidate_name=candidate['name'],
                candidate_email=candidate['email'],
                interview_time=interview_time,
                phone=candidate['phone'],
                candidate_id=candidate_id
            )
            logger.info(f"Interview scheduled successfully: {event['id']}")
        except Exception as calendar_error:
            logger.error(f"Google Calendar scheduling failed: {calendar_error}")
            raise HTTPException(
                status_code=500,
                detail="Failed to schedule in calendar. Please try again."
            )


        # Update candidate in database
        update_result = await candidates_collection.update_one(
            {"_id": ObjectId(candidate_id)},
            {
                "$set": {
                    "status": "Interview Scheduled",
                    "interview_time": interview_time,
                    "calendar_event_id": event['id'],
                    "updated_at": datetime.utcnow()
                }
            }
        )

        if update_result.modified_count == 0:
            logger.error(f"MongoDB update failed for candidate {candidate_id}")
            raise HTTPException(status_code=500, detail="Failed to update candidate status")
        else:
            logger.info(f"Candidate {candidate_id} updated successfully in the database")


        return {
            "status": "success",
            "message": "Interview scheduled successfully",
            "event_id": event['id']
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scheduling interview: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to schedule interview. Please try again."
        )
