import asyncio
import datetime
import logging
import requests
from decouple import config
from app.google_calendar import get_calendar_service
import logging
import os
import whisper
import os
import json
import time  # Ensure time is imported
from app.config import TELNYX_API_KEY, TELNYX_CONNECTION_ID, TELNYX_PHONE_NUMBER, WEBHOOK_URL
from app.questions import QUESTIONS
from app.database import candidates_collection
from bson import ObjectId
import speech_recognition as sr
from pydub import AudioSegment
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pydub.utils import which
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydub import AudioSegment
from app.database import get_interview_result

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELNYX_CALL_URL = config("WEBHOOK_URL", default="http://localhost:8000/telnyx/start-interview")

DOWNLOADS_FOLDER = "recordings"
os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)  # Ensure folder exists

# Ensure FFmpeg paths are correctly set
AudioSegment.converter = which("ffmpeg") or "C:/ffmpeg/bin/ffmpeg.exe"
AudioSegment.ffprobe = which("ffprobe") or "C:/ffmpeg/bin/ffprobe.exe"

# Create output directory if it doesn't exist
OUTPUT_DIR = "converted_audio"
os.makedirs(OUTPUT_DIR, exist_ok=True)

recording_ids = []  # Global list to store recording IDs

async def fetch_upcoming_interviews():
    """Fetch upcoming interviews from Google Calendar."""
    try:
        logger.info("📅 Fetching upcoming interviews from Google Calendar...")
        service = get_calendar_service()
        if not service:
            raise Exception("Google Calendar service unavailable")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)).isoformat()

        logger.info(f"🔍 Checking events between {now} and {future}")

        events_result = service.events().list(
            calendarId='primary',
            timeMin=now,
            timeMax=future,
            singleEvents=True,
            orderBy='startTime'
        ).execute()

        events = events_result.get('items', [])
        upcoming_interviews = []

        for event in events:
            summary = event.get('summary', '')
            description = event.get('description', '')
            start_time = event['start']['dateTime']
            logger.info(f"📄 Found event: {summary} at {start_time}")

            if 'Interview Call' in summary:
                phone_number = summary.split('-')[-1].strip()
                interview_id = None
                for line in description.split("\n"):
                    if "Interview ID" in line:
                        interview_id = line.split(":")[-1].strip()
                        break

                if phone_number and interview_id:
                    upcoming_interviews.append({
                        "phone": phone_number,
                        "interview_time": start_time,
                        "interview_id": interview_id
                    })

        logger.info(f"📦 Total upcoming interviews found: {len(upcoming_interviews)}, {upcoming_interviews}")
        return upcoming_interviews

    except Exception as e:
        logger.error(f"❌ Error fetching interviews: {e}")
        return []


async def trigger_telnyx_call(phone, interview_id):
    """Trigger Telnyx call via HTTP POST."""
    try:
        logger.info(f"📲 Triggering call for phone={phone}, interview_id={interview_id}")
        response = requests.post(
            TELNYX_CALL_URL,
            json={"phone_number": phone, "interview_id": interview_id}
        )
        if response.status_code == 200:
            logger.info(f"✅ Call successfully triggered for {phone}")
        else:
            logger.error(f"❌ Failed to trigger call for {phone}: {response.text}")
    except Exception as e:
        logger.error(f"❌ Telnyx call error: {e}")


async def monitor_calendar():
    """Run one scan cycle (scheduled every minute)."""
    try:
        logger.info("🔄 Running monitor_calendar check...")
        interviews = await fetch_upcoming_interviews()
        current_time = datetime.datetime.now(datetime.timezone.utc)
        logger.info(f"🕒 Current UTC time: {current_time.isoformat()}")

        for interview in interviews:
            interview_time_str = interview['interview_time']
            interview_time = datetime.datetime.fromisoformat(interview_time_str.replace("Z", "+00:00"))

            candidate = await candidates_collection.find_one({"_id": ObjectId(interview["interview_id"])})
            logger.info(f"⏰ Comparing current time with interview_time: {interview_time.isoformat()}")

            if candidate and candidate.get("call_triggered"):
                logger.info(f"⛔ Call already triggered for interview_id {interview['interview_id']}. Skipping.")
                continue

            if current_time >= interview_time:
                logger.info(f"🚀 Launching call for interview at {interview_time}")
                await trigger_telnyx_call(interview["phone"], interview["interview_id"])

                 # Mark the candidate as called
                await candidates_collection.update_one(
                    {"_id": ObjectId(interview["interview_id"])},
                    {"$set": {"call_triggered": True}}
                )

                if interview["phone"] and interview["interview_id"]:
                    await run_interview_flow(interview["phone"])
            else:
                logger.info(f"🕓 Not time yet for interview at {interview_time}")

    except Exception as e:
        logger.error(f"❌ Error in monitor cycle: {e}")


async def initiate_call(to_number):
    """Initiates a call and waits for it to be fully answered before proceeding."""
    url = "https://api.telnyx.com/v2/calls"
    headers = {"Authorization": f"Bearer {TELNYX_API_KEY}", "Content-Type": "application/json"}

    payload = {
        "connection_id": TELNYX_CONNECTION_ID,
        "to": to_number,
        "from": TELNYX_PHONE_NUMBER,
        "webhook_url": WEBHOOK_URL
    }

    # ✅ Log the payload
    logger.info(f"📦 Payload being sent to Telnyx:\n{json.dumps(payload, indent=2)}")

    response = requests.post(url, headers=headers, json=payload)
    data = response.json()

    if "data" in data and "call_control_id" in data["data"]:  
        initial_call_id = data["data"]["call_control_id"]
        print(f"📞 Call initiated: {initial_call_id}")

        # Wait until call is answered, then get latest call ID
        updated_call_id = await wait_for_answer(initial_call_id)

        if updated_call_id:
            return updated_call_id  # Use latest call ID
        else:
            print("⚠ Call not fully established. Exiting.")
            return None
    else:
        print(f"❌ Failed to initiate call. Response: {json.dumps(data, indent=2)}")
        return None

async def get_latest_call_state(call_id, retries=3, delay=2):
    """Fetches the latest call details from Telnyx with retries."""
    url = f"https://api.telnyx.com/v2/calls/{call_id}"
    headers = {"Authorization": f"Bearer {TELNYX_API_KEY}"}

    for attempt in range(retries):
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            return response.json().get("data", {})

        print(f"⚠ Failed to fetch call state (attempt {attempt+1}/{retries}): {response.json()}")
        time.sleep(delay)  # Wait before retrying

    print("❌ All attempts to fetch call state failed.")
    return None

async def wait_for_answer(call_id, timeout=30):
    """Waits until the call is marked as answered (`is_alive: true`) before proceeding."""
    for _ in range(timeout // 2):
        call_data = await get_latest_call_state(call_id)

        if call_data and call_data.get("is_alive", False):
            print("✅ Call is alive! Fetching latest Call Control ID...")

            # Fetch the latest call_control_id (sometimes it updates after answering)
            time.sleep(2)  # Extra delay for stability
            latest_data = await get_latest_call_state(call_id)
            if latest_data:
                updated_call_id = latest_data["call_control_id"]

                print(f"🔄 Updated Call Control ID: {updated_call_id}")
                return updated_call_id  # Return the updated ID

        time.sleep(2)  # Wait before checking again

    print("⚠ Call was never fully answered. Exiting.")
    return None

async def wait_for_call_ready(call_id, timeout=10):
    """Waits for the call to be in a ready state to receive audio commands."""
    for _ in range(timeout):
        call_data = await get_latest_call_state(call_id)

        if call_data and call_data.get("is_alive", False):
            print("✅ Call is fully established and ready to receive speech.")
            return True

        time.sleep(1)  # Wait before checking again

    print("⚠ Call never reached a ready state. Exiting.")
    return False

async def play_questions(call_id):
    """Ensures the call is active, then plays introduction, waits, starts recording, and asks questions."""
    url = f"https://api.telnyx.com/v2/calls/{call_id}/actions/speak"
    headers = {"Authorization": f"Bearer {TELNYX_API_KEY}", "Content-Type": "application/json"}

    # ✅ Step 2: Play Introduction
    intro_text = "Hello! This is an automated interview call. You will be asked a few questions. Please answer after each question. Let's begin."
    intro_payload = {"payload": intro_text, "voice": "female", "language": "en-US"}
    
    # ✅ Step 1: Ensure call is fully active
    if not await wait_for_call_ready(call_id):
        print("⚠ Call not ready to receive audio. Exiting.")
        return  
     # Wait until call is answered, then get latest call ID
    response = requests.post(url, headers=headers, json=intro_payload)
    print("🎤 Introduction given.")
    print("✅ Call is fully established and ready to receive speech.")
    # ✅ Step 3: Delay before first question
    print("⏳ Waiting 5 seconds before starting...")
    time.sleep(5)  
    # ✅ Step 4: Start asking questions and recording responses
    for i, question in enumerate(QUESTIONS):
        latest_data = await get_latest_call_state(call_id)
        if not latest_data or not latest_data.get("is_alive", False):
            print("⚠ Call has ended. Stopping questions.")
            return
        
        print(f"📢 Asking Question {i+1}: {question}")
        question_payload = {"payload": question, "voice": "female", "language": "en-US"}
        response = requests.post(url, headers=headers, json=question_payload)

        if response.status_code == 204 or response.json().get("data", {}).get("result") == "ok":
            print(f"✅ Question {i+1} delivered.")
        else:
            print(f"❌ Failed to ask Question {i+1}: {response.json()}")

        time.sleep(3)  # ✅ Short pause after speaking question

        # ✅ Start recording **after** the 1st question
        if i == 0 or i == 1 or i == 2:
            print(f"🎙 Starting recording after Question {i+1}...")
            await start_recording(call_id)

        time.sleep(30)  # ✅ Allow time for response

        # ✅ Stop recording **before** next question
        if i == 0 or i == 1 or i == 2:
            print(f"⏹ Stopping recording before Question {i+2}...")
            await stop_recording(call_id)
    time.sleep(3)
    # ✅ Step 5: Play Closing Statement
    closing_text = "Thank you for your time. Your responses have been recorded. We will review them and get back to you soon. Have a great day!"
    closing_payload = {"payload": closing_text, "voice": "female", "language": "en-US"}
    response = requests.post(url, headers=headers, json=closing_payload)
    print("🎤 Closing statement given.")
    time.sleep(3)
    # ✅ Step 6: Hang up the call
    print("📞 Hanging up the call...")
    await hangup_call(call_id)


async def start_recording(call_id):
    """Start recording the call after ensuring the latest call_control_id is used."""
    time.sleep(5)  # Ensure call is stable

    # Fetch the latest call state before recording
    latest_data = await get_latest_call_state(call_id)
    if not latest_data or not latest_data.get("is_alive", False):
        print("⚠ Call is not alive. Skipping recording.")
        return

    call_id = latest_data["call_control_id"]  # Ensure latest ID
    print(f"🔄 Using updated Call Control ID for recording: {call_id}")

    url = f"https://api.telnyx.com/v2/calls/{call_id}/actions/record_start"
    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "format": "wav",  # Supported: mp3, wav
        "channels": "dual",  # 'single' or 'dual'
        "play_beep": True,  # Optionally notify that recording started
        "noise_suppression": False
#        "duration": 300 # Set recording duration (600 seconds = 10 min)
    }

#    time.sleep(5)
    response = requests.post(url, headers=headers, json=payload)
    response_data = response.json()
        
    if response.status_code == 200 and response_data.get("data", {}).get("result") == "ok":
        recording_id = response_data["data"]["recording_id"]
        print(f"🎙 Recording started successfully on retry! Recording ID: {recording_id}")
        # ✅ Store the recording ID
        recording_ids.append(recording_id) 
    else:
        print(f"❌ Recording retry also failed: {response_data}")

async def stop_recording(call_id):
    """Stops the active recording for the given call."""
    url = f"https://api.telnyx.com/v2/calls/{call_id}/actions/record_stop"
    headers = {
        "Authorization": f"Bearer {TELNYX_API_KEY}",
        "Content-Type": "application/json"
    }

    response = requests.post(url, headers=headers)
    response_data = response.json()

    if response.status_code == 200 and response_data.get("data", {}).get("result") == "ok":
        print(f"⏹ Recording stopped successfully for call {call_id}")
    else:
        print(f"❌ Failed to stop recording: {response_data}")


async def hangup_call(call_id):
    """Attempts to hang up the call using Telnyx API"""
    url = f"https://api.telnyx.com/v2/calls/{call_id}/actions/hangup"
    headers = {"Authorization": f"Bearer {TELNYX_API_KEY}"}

    response = requests.post(url, headers=headers)

    # Extract the JSON response
    response_json = response.json()

    if response.status_code == 200 and response_json.get('data', {}).get('result') == 'ok':
        print("✅ Call hung up successfully!")
        return True
    else:
        print(f"❌ Failed to hang up call: {response_json}")
        return False


async def get_recording_url(recording_id):
    """Fetches the download URL for a given recording."""
    url = f"https://api.telnyx.com/v2/recordings/{recording_id}"
    headers = {"Authorization": f"Bearer {TELNYX_API_KEY}"}

    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        data = response.json()
        download_url = data.get("data", {}).get("url")
        if download_url:
            print(f"🎙 Download your recording here: {download_url}")
            return download_url
        else:
            print("⚠ Recording URL not found.")
    else:
        print(f"❌ Failed to fetch recording. Response: {response.json()}")

async def merge_recordings(recording_files, folder_name, output_filename):
    """Merge multiple audio files into a single file."""
    if not recording_files:
        print("❌ No recordings to merge.")
        return

    interviews = await fetch_upcoming_interviews()
    interview_id = interviews[0]["interview_id"] 

    combined_audio = AudioSegment.empty()

    for file in recording_files:
        if os.path.exists(file):
            audio = AudioSegment.from_wav(file)
            combined_audio += audio + AudioSegment.silent(duration=1000)  # Add 1-second silence between answers
    output_path = os.path.join(DOWNLOADS_FOLDER, folder_name, output_filename)
    combined_audio.export(output_path, format="wav")
    if os.path.exists(output_path):
            print(f"🎧 Final merged interview recording is ready: {output_path}")
    else:
        print("⚠ Final recording not found.")
    return await process_candidate_response(output_path, interview_id)

async def fetch_recording_url(recording_id, max_retries=5, wait_time=5):
    """Fetch the recording URL from Telnyx using the recording ID."""

    # ✅ Introduce an initial delay to ensure the recording is processed
    init_delay = 20  # Adjust if needed
    print(f"⏳ Waiting {init_delay} seconds before fetching the recording URL...")
    time.sleep(init_delay)

    print(f"🔍 Attempting to fetch recording URL for Recording ID: {recording_id}")  # ✅ Debugging line
    url = f"https://api.telnyx.com/v2/recordings/{recording_id}"
    headers = {"Authorization": f"Bearer {TELNYX_API_KEY}"}

    # ✅ Introduce an initial delay to ensure the recording is processed
    initial_delay = 20  # Adjust if needed
    print(f"⏳ Waiting {initial_delay} seconds before fetching the recording URL...")
    time.sleep(initial_delay)

    for attempt in range(max_retries):
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            data = response.json()
            recording_url = data.get("data", {}).get("download_urls", {}).get("wav")
            if recording_url:
                print(f"🎙 Recording URL: {recording_url}")
                return recording_url
            else:
                print(f"⚠ Recording URL not found. Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
        else:
            print(f"❌ Failed to fetch recording URL: {response.json()}")
            return None

    print("❌ Giving up on fetching the recording URL.")
    return None

async def download_recording(recording_url, folder_name, filename):
    """Download the recording file from the provided URL."""
    if not recording_url:
        print("❌ No recording URL provided. Skipping download.")
        return None

    response = requests.get(recording_url)

    if response.status_code == 200:
        file_path = os.path.join(DOWNLOADS_FOLDER, folder_name, filename)
        with open(file_path, "wb") as file:
            file.write(response.content)
        print(f"✅ Recording saved as {file_path}")
        return file_path
    else:
        print("❌ Failed to download the recording.")
        return None

async def retrieve_and_merge_recordings(recording_ids):
    """Fetch, download, and merge recordings."""
    interviews = await fetch_upcoming_interviews()
    interview_id = interviews[0]["interview_id"]
    folder_name = f"{interview_id}"
    os.makedirs(os.path.join(DOWNLOADS_FOLDER, folder_name), exist_ok=True)

    recording_files = []

    print(f"📢 Processing {len(recording_ids)} recordings: {recording_ids}")  # ✅ Debugging line

    for index, recording_id in enumerate(recording_ids):
        print(f"🔍 Fetching recording {index + 1}/{len(recording_ids)} with ID: {recording_id}")  # ✅ Debugging line

        recording_url = await fetch_recording_url(recording_id)
        if recording_url:
            filename = f"question_{index + 1}.wav"
            file_path = await download_recording(recording_url, folder_name, filename)
            if file_path:
                recording_files.append(file_path)
    if recording_files:
        await merge_recordings(recording_files, folder_name, output_filename = f"{interview_id}.wav")
    else:
        print("❌ No recordings were successfully downloaded. Merge skipped.")

async def run_interview_flow(to_number):
    call_id = await initiate_call(to_number)
    if call_id:
        time.sleep(3)
        await play_questions(call_id)
        
        print("⏳ Waiting for recordings to be received and processed...")
        await asyncio.sleep(60)

        if recording_ids:
            await retrieve_and_merge_recordings(recording_ids)
        else:
            print("⚠ No recordings captured.")
        
        return call_id
    else:
        return None

async def convert_audio_to_wav(input_path):
    """ Converts audio to WAV format, saves in 'converted_audio/' folder. """
    interviews = await fetch_upcoming_interviews()
    interview_id = interviews[0]["interview_id"]

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"❌ File not found: {input_path}")

    output_wav = os.path.join(OUTPUT_DIR, f"{interview_id}_output.wav")

    if input_path.endswith(".wav"):
        print(f"🎵 Using WAV file directly: {input_path}")
        return input_path  

    elif input_path.endswith(".mp4"):
        audio = AudioSegment.from_file(input_path, format="mp4")

    elif input_path.endswith(".mp3"):
        audio = AudioSegment.from_mp3(input_path)

    else:
        raise ValueError("❌ Unsupported file format. Use MP3, MP4, or WAV.")

    audio.export(output_wav, format="wav")
    print(f"✅ Converted {input_path} → {output_wav}")
    return output_wav  

### **2️⃣ Transcribe Audio (Speech-to-Text)**
async def transcribe_audio(wav_path, use_whisper=True):
    """ Uses Whisper or Google Speech Recognition to transcribe speech. """
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"❌ WAV file not found: {wav_path}")

    if use_whisper:
        model = whisper.load_model("base")  
        result = model.transcribe(wav_path)
        transcript = result["text"].strip()
        print(f"📝 Whisper Transcription: {transcript}")
        return transcript
    else:
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        try:
            transcript = recognizer.recognize_google(audio_data).strip()
            print(f"📝 Google Speech Transcription: {transcript}")
            return transcript
        except sr.UnknownValueError:
            print("⚠️ Google Speech Recognition could not understand the audio.")
            return None
        except sr.RequestError:
            print("⚠️ Google Speech Recognition request failed.")
            return None

### **3️⃣ Evaluate Response using Cosine Similarity**
async def evaluate_response(candidate_response, ideal_response):
    """ Compares candidate's response with ideal answer using cosine similarity. """
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform([candidate_response, ideal_response])
    score = cosine_similarity(tfidf_matrix[0], tfidf_matrix[1])[0][0] * 10  
    return round(score, 2)

### **4️⃣ Categorize Candidate Response**
async def categorize_score(score):
    """ Categorizes response based on score. """
    if score >= 8:
        return "Excellent"
    elif score >= 5:
        return "Good"
    else:
        return "Below Average"

### **🏁 Main Function**
async def process_candidate_response(audio_file, interview_id, use_whisper=True):
    """ Full pipeline: Convert → Transcribe → Evaluate → Categorize """

    # Step 1: Convert to WAV
    wav_file = await convert_audio_to_wav(audio_file)

    # Step 2: Speech-to-Text
    candidate_response = await transcribe_audio(wav_file, use_whisper)
    if not candidate_response:
        return {"error": "Failed to transcribe audio."}

    # Step 3: Evaluate & Categorize
    ideal_response = """
Supervised learning is a type of machine learning where the model is trained using labeled data. 
This means that each training example includes an input and the correct output, allowing the algorithm 
to learn a mapping between them. It's commonly used in tasks like classification and regression.

Unsupervised learning, on the other hand, uses data that has no labels. 
The algorithm tries to learn the underlying structure or distribution in the data, often used in 
clustering and dimensionality reduction tasks.

I have hands-on experience implementing both types using Python. 
In my projects, I’ve applied supervised methods for predictive modeling and unsupervised techniques 
for data exploration and pattern recognition, especially in NLP and computer vision contexts.
"""

    score = await evaluate_response(candidate_response, ideal_response)
    category = await categorize_score(score)
    if score >= 8 :
        status = "Interview Selected"

    elif score >=5 :
        status = "Interview Not Selected, Under Review"

    else :
        status = "Rejected"

        # Step 4: Save results to DB
    await candidates_collection.update_one(
        {"_id": ObjectId(interview_id)},
        {"$set": {
            "transcription": candidate_response,
            "score": score,
            "category": category,
            "status" : status
        }}
    )

    return {
        "transcribed_text": candidate_response,
        "score": score,
        "category": category,
        "status" : status
    }

def fetch_interview_result(interview_id):
    result = get_interview_result(interview_id)
    print(f"Fetched result for Interview ID {interview_id}: {result}")  # Print the result to the console
    return result
