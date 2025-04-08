from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from bson import ObjectId
import os.path
import pickle
from datetime import datetime, timedelta
import logging
from app.database import candidates_collection
import asyncio
from decouple import config
import requests
import os
import whisper
import speech_recognition as sr
from pydub import AudioSegment
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pydub.utils import which

logger = logging.getLogger(__name__)

SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.pickle'

def get_calendar_service():
    """Initialize and return Google Calendar service"""
    creds = None
    try:
        # Check if token file exists
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'rb') as token:
                creds = pickle.load(token)

        # If no valid credentials available, let user log in
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_FILE):
                    logger.error(f"Missing {CREDENTIALS_FILE}")
                    raise FileNotFoundError(f"{CREDENTIALS_FILE} not found")
                    
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=56137)
            
            # Save the credentials for the next run
            with open(TOKEN_FILE, 'wb') as token:
                pickle.dump(creds, token)

        # Build and return the service
        service = build('calendar', 'v3', credentials=creds)
        return service

    except Exception as e:
        logger.error(f"Error initializing Google Calendar API: {e}")
        return None

async def schedule_interview(candidate_id: str, interview_time: str):
    """Schedule interview and create calendar event with phone number in title"""
    try:
        service = get_calendar_service()
        if not service:
            raise Exception("Google Calendar service unavailable")

        # Get candidate details
        candidate = await candidates_collection.find_one({"_id": ObjectId(candidate_id)})
        if not candidate:
            raise Exception("Candidate not found")

        # Format phone number for event title
        phone = candidate.get('phone', '').replace('-', '').replace('+', '')
        
        # Create calendar event
        event = {
            'summary': f"Interview Call - {candidate['name']} - {phone}",
            'description': (
                f"Interview for {candidate.get('position', 'position')}\n"
                f"Phone: {candidate['phone']}\n"
                f"Email: {candidate.get('email', 'N/A')}\n"
                f"ID: {candidate_id}"
            ),
            'start': {
                'dateTime': interview_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': (
                    datetime.fromisoformat(interview_time.replace('Z', '')) + 
                    timedelta(minutes=30)
                ).isoformat() + 'Z',
                'timeZone': 'UTC',
            },
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'popup', 'minutes': 15},
                ]
            }
        }

        event = service.events().insert(
            calendarId='primary',
            body=event
        ).execute()

        # Update candidate record
        await candidates_collection.update_one(
            {"_id": ObjectId(candidate_id)},
            {
                "$set": {
                    "status": "Interview Scheduled",
                    "interview_time": interview_time,
                    "calendar_event_id": event['id']
                }
            }
        )

        logger.info(f"Interview scheduled for candidate {candidate_id}")
        return event

    except Exception as e:
        logger.error(f"Error scheduling interview: {e}")
        raise

async def schedule_interview_event(candidate_name: str, candidate_email: str, 
                                 interview_time: str, phone: str, candidate_id: str):
    try:
        service = get_calendar_service()
        if not service:
            raise Exception("Failed to initialize Google Calendar service")

        from decouple import config
        base_url = config('BASE_URL', default='http://localhost:8000')
        
        # Update to use Telnyx endpoint instead of Twilio
        interview_link = f"{base_url}/telnyx/start-interview/{candidate_id}"
        
        event = {
            'summary': f'Interview Call - {candidate_name} - {phone}',
            'description': f"""
Interview for {candidate_name}
Phone: {phone}
Email: {candidate_email}

Important Instructions:
1. The system will automatically call you at the scheduled time
2. No action is required from your side
3. Please ensure:
   - You are in a quiet environment
   - You have good phone reception
   - You are ready 5 minutes before the scheduled time
   - You speak clearly during the interview

Interview ID: {candidate_id}
            """.strip(),
            'start': {
                'dateTime': interview_time,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': (datetime.fromisoformat(interview_time.replace('Z', '')) + 
                           timedelta(minutes=30)).isoformat() + 'Z',
                'timeZone': 'UTC',
            },
            'attendees': [
                {'email': candidate_email},
            ],
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 30},
                ],
            },
        }

        created_event = service.events().insert(
            calendarId='primary',
            body=event,
            sendUpdates='all'
        ).execute()

        logger.info(f"Interview scheduled for {candidate_name} at {interview_time}")
        return created_event

    except Exception as e:
        logger.error(f"Error scheduling calendar event: {e}")
        raise

async def get_available_slots(start_date: datetime, days: int = 7):
    """Get available interview slots"""
    try:
        service = get_calendar_service()
        if not service:
            raise Exception("Google Calendar service unavailable")

        end_date = start_date + timedelta(days=days)
        
        # Get existing events
        events_result = service.events().list(
            calendarId='primary',
            timeMin=start_date.isoformat() + 'Z',
            timeMax=end_date.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        
        busy_slots = [
            (
                datetime.fromisoformat(event['start'].get('dateTime', event['start'].get('date'))),
                datetime.fromisoformat(event['end'].get('dateTime', event['end'].get('date')))
            )
            for event in events_result.get('items', [])
        ]

        # Generate available slots
        available_slots = []
        current = datetime.utcnow().replace(minute=0, second=0, microsecond=0, tzinfo=None)
        
        while current < end_date:
#            if current.weekday() < 5:  # Monday-Friday
#                for hour in range(9, 17):  # 9 AM to 5 PM
#                    slot_start = current.replace(hour=hour, minute=0)
#                    slot_end = slot_start + timedelta(minutes=30)

            slot_start = current
            slot_end = slot_start + timedelta(minutes=30)
                    
                    # Check if slot is available
#                    if not any(
#                        busy_start <= slot_start < busy_end
#                        for busy_start, busy_end in busy_slots
#                    ):
#                        available_slots.append({
#                            'start': slot_start.isoformat() + 'Z',
#                            'end': slot_end.isoformat() + 'Z'
#                        })
            available_slots.append({
                'start': slot_start.isoformat() + 'Z',
                'end': slot_end.isoformat() + 'Z'
            })
            
#            current = current.replace(hour=0, minute=0) + timedelta(days=1)
            current += timedelta(minutes=30)

        return available_slots

    except Exception as e:
        logger.error(f"Error getting available slots: {e}")
        raise


#async def trigger_calendar_check():
#    """Trigger the Google Apps Script to check for scheduled interviews"""
#    script_url = config('GOOGLE_SCRIPT_URL')
#    
#    try:
#        response = requests.get(script_url)
#        if response.status_code == 200:
#            logger.info("Successfully triggered calendar check")
#            return True
#        else:
#            logger.error(f"Failed to trigger calendar check: {response.status_code}")
#            return False
#    except Exception as e:
#        logger.error(f"Error triggering calendar check: {e}")
#        return False
