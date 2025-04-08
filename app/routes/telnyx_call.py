import requests
import os
import json
import time  # Ensure time is imported
from app.config import TELNYX_API_KEY, TELNYX_CONNECTION_ID, TELNYX_PHONE_NUMBER, WEBHOOK_URL
from app.questions import QUESTIONS
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from pydub import AudioSegment

# Router setup
router = APIRouter()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DOWNLOADS_FOLDER = "recordings"
os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)  # Ensure folder exists

recording_ids = []  # Global list to store recording IDs

def initiate_call(to_number):
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
        updated_call_id = wait_for_answer(initial_call_id)

        if updated_call_id:
            return updated_call_id  # Use latest call ID
        else:
            print("⚠ Call not fully established. Exiting.")
            return None
    else:
        print(f"❌ Failed to initiate call. Response: {json.dumps(data, indent=2)}")
        return None

def get_latest_call_state(call_id, retries=3, delay=2):
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

def wait_for_answer(call_id, timeout=30):
    """Waits until the call is marked as answered (`is_alive: true`) before proceeding."""
    for _ in range(timeout // 2):
        call_data = get_latest_call_state(call_id)

        if call_data and call_data.get("is_alive", False):
            print("✅ Call is alive! Fetching latest Call Control ID...")

            # Fetch the latest call_control_id (sometimes it updates after answering)
            time.sleep(2)  # Extra delay for stability
            latest_data = get_latest_call_state(call_id)
            if latest_data:
                updated_call_id = latest_data["call_control_id"]
                print(f"🔄 Updated Call Control ID: {updated_call_id}")
                return updated_call_id  # Return the updated ID

        time.sleep(2)  # Wait before checking again

    print("⚠ Call was never fully answered. Exiting.")
    return None

def wait_for_call_ready(call_id, timeout=10):
    """Waits for the call to be in a ready state to receive audio commands."""
    for _ in range(timeout):
        call_data = get_latest_call_state(call_id)

        if call_data and call_data.get("is_alive", False):
            print("✅ Call is fully established and ready to receive speech.")
            return True

        time.sleep(1)  # Wait before checking again

    print("⚠ Call never reached a ready state. Exiting.")
    return False

def play_questions(call_id):
    """Ensures the call is active, then plays introduction, waits, starts recording, and asks questions."""
    url = f"https://api.telnyx.com/v2/calls/{call_id}/actions/speak"
    headers = {"Authorization": f"Bearer {TELNYX_API_KEY}", "Content-Type": "application/json"}

    # ✅ Step 1: Ensure call is fully active
    if not wait_for_call_ready(call_id):
        print("⚠ Call not ready to receive audio. Exiting.")
        return  

    print("✅ Call is fully established and ready to receive speech.")

    # ✅ Step 2: Play Introduction
    intro_text = "Hello! This is an automated interview call. You will be asked a few questions. Please answer after each question. Let's begin."
    intro_payload = {"payload": intro_text, "voice": "female", "language": "en-US"}
    
    response = requests.post(url, headers=headers, json=intro_payload)
    print("🎤 Introduction given.")

    # ✅ Step 3: Delay before first question
    print("⏳ Waiting 5 seconds before starting...")
    time.sleep(5)  

    # ✅ Step 4: Start asking questions and recording responses
    for i, question in enumerate(QUESTIONS):
        latest_data = get_latest_call_state(call_id)
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
            start_recording(call_id)

        time.sleep(30)  # ✅ Allow time for response

        # ✅ Stop recording **before** next question
        if i == 0 or i == 1 or i == 2:
            print(f"⏹ Stopping recording before Question {i+2}...")
            stop_recording(call_id)

    # ✅ Step 5: Play Closing Statement
    closing_text = "Thank you for your time. Your responses have been recorded. We will review them and get back to you soon. Have a great day!"
    closing_payload = {"payload": closing_text, "voice": "female", "language": "en-US"}
    response = requests.post(url, headers=headers, json=closing_payload)
    print("🎤 Closing statement given.")

    # ✅ Step 6: Hang up the call
    print("📞 Hanging up the call...")
    hangup_call(call_id)


def start_recording(call_id):
    """Start recording the call after ensuring the latest call_control_id is used."""
    time.sleep(5)  # Ensure call is stable

    # Fetch the latest call state before recording
    latest_data = get_latest_call_state(call_id)
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

    time.sleep(5)
    response = requests.post(url, headers=headers, json=payload)
    response_data = response.json()
        
    if response.status_code == 200 and response_data.get("data", {}).get("result") == "ok":
        recording_id = response_data["data"]["recording_id"]
        print(f"🎙 Recording started successfully on retry! Recording ID: {recording_id}")
        # ✅ Store the recording ID
        recording_ids.append(recording_id) 
    else:
        print(f"❌ Recording retry also failed: {response_data}")

def stop_recording(call_id):
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


def hangup_call(call_id):
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


def get_recording_url(recording_id):
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

def merge_recordings(recording_files, output_filename="final_interview.wav"):
    """Merge multiple audio files into a single file."""
    if not recording_files:
        print("❌ No recordings to merge.")
        return

    combined_audio = AudioSegment.empty()

    for file in recording_files:
        if os.path.exists(file):
            audio = AudioSegment.from_wav(file)
            combined_audio += audio + AudioSegment.silent(duration=1000)  # Add 1-second silence between answers

    output_path = os.path.join(DOWNLOADS_FOLDER, output_filename)
    combined_audio.export(output_path, format="wav")
    print(f"🎙 Final merged recording saved as {output_path}")

def fetch_recording_url(recording_id, max_retries=5, wait_time=5):
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

def download_recording(recording_url, filename):
    """Download the recording file from the provided URL."""
    if not recording_url:
        print("❌ No recording URL provided. Skipping download.")
        return None

    response = requests.get(recording_url)

    if response.status_code == 200:
        file_path = os.path.join(DOWNLOADS_FOLDER, filename)
        with open(file_path, "wb") as file:
            file.write(response.content)
        print(f"✅ Recording saved as {file_path}")
        return file_path
    else:
        print("❌ Failed to download the recording.")
        return None

def retrieve_and_merge_recordings(recording_ids):
    """Fetch, download, and merge recordings."""
    recording_files = []

    print(f"📢 Processing {len(recording_ids)} recordings: {recording_ids}")  # ✅ Debugging line

    for index, recording_id in enumerate(recording_ids):
        print(f"🔍 Fetching recording {index + 1}/{len(recording_ids)} with ID: {recording_id}")  # ✅ Debugging line

        recording_url = fetch_recording_url(recording_id)
        if recording_url:
            filename = f"question_{index + 1}.wav"
            file_path = download_recording(recording_url, filename)
            if file_path:
                recording_files.append(file_path)

    print("🔄 Merging all recordings...")
    merge_recordings(recording_files, "final_interview.wav")

def run_interview_flow(to_number):
    call_id = initiate_call(to_number)
    
    if call_id:
        time.sleep(3)
        play_questions(call_id)
        
        print("⏳ Waiting for recordings to be received and processed...")
        time.sleep(120)

        if recording_ids:
            retrieve_and_merge_recordings(recording_ids)
        else:
            print("⚠ No recordings captured.")
        
        final_path = os.path.join(DOWNLOADS_FOLDER, "final_interview.wav")
        if os.path.exists(final_path):
            print(f"🎧 Final interview recording is ready: {final_path}")
        else:
            print("⚠ Final recording not found.")
        
        return call_id
    else:
        return None
    
# ------------------- API Endpoint -------------------

class InterviewRequest(BaseModel):
    to_number: str

@router.post("/start-interview")
def start_interview(request: InterviewRequest):
    try:
        call_id = run_interview_flow(request.to_number)
        if call_id:
            return {"status": "success", "call_id": call_id}
        raise HTTPException(status_code=500, detail="Call failed or interview not recorded.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


#if __name__ == "__main__":
#    call_id = run_interview_flow(to_number = "+919544176361")