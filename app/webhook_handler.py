from flask import Flask, request, jsonify
import requests
import os
import json
from pydub import AudioSegment  # Ensure you have `pydub` installed
from config import TELNYX_API_KEY

app = Flask(__name__)

RECORDING_LIST = []  # ✅ Store received recording file paths

# Define the folder to save recordings
DOWNLOADS_FOLDER = "recordings"
os.makedirs(DOWNLOADS_FOLDER, exist_ok=True)  # ✅ Ensure folder exists

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook events from Telnyx."""
    data = request.json
    print(f"📡 Webhook received: {json.dumps(data, indent=2)}")  # ✅ Log all incoming events

    # 👇 Accept testing format for development
    if 'phone_number' in data and 'interview_id' in data:
        print(f"✅ Test webhook received for {data['phone_number']}, Interview ID: {data['interview_id']}")
        return jsonify({"status": "test-received"}), 200

    if not data or 'data' not in data:
        print("⚠ Invalid webhook payload received.")
        return jsonify({"status": "error", "message": "Invalid payload"}), 400

    event = data['data']
    event_type = event.get('event_type', '')

    if event_type == 'call.recording.saved':  # ✅ Correct event for saved recordings
        recording_urls = event.get('payload', {}).get('recording_urls', {})
        recording_url = recording_urls.get('wav', None)  # Extract WAV URL safely

        if recording_url:
            print(f"Recording URL: {recording_url}")
        else:
            print("No recording URL found")


    elif event_type == 'call.completed':  # ✅ Call completed event
        call_control_id = event.get('payload', {}).get('call_control_id', 'Unknown')
        print(f"📞 Call {call_control_id} completed.")

    else:
        print(f"ℹ Received unrelated event: {event_type}")

    return jsonify({"status": "received"}), 200

def merge_recordings():
    """Merge all recorded audio files into one."""
    if len(RECORDING_LIST) < 2:
        print("⚠ Not enough recordings to merge.")
        return

    print(f"🔄 Merging {len(RECORDING_LIST)} recordings...")

    combined = AudioSegment.empty()
    for file_path in RECORDING_LIST:
        audio = AudioSegment.from_file(file_path, format="mp3")
        combined += audio  # Append each recording

    final_output = os.path.join(DOWNLOADS_FOLDER, "combined_recording.mp3")
    combined.export(final_output, format="mp3")
    print(f"✅ Combined recording saved: {final_output}")

def download_recording(recording_url, recording_id):
    """Download the recording and save it locally, then attempt to merge."""
    try:
        file_name = f"call_recording_{recording_id}.mp3"
        file_path = os.path.join(DOWNLOADS_FOLDER, file_name)

        headers = {"Authorization": f"Bearer {TELNYX_API_KEY}"}
        response = requests.get(recording_url, headers=headers)

        if response.status_code == 200:
            with open(file_path, 'wb') as file:
                file.write(response.content)
            print(f"✅ Recording saved: {file_path}")

            RECORDING_LIST.append(file_path)  # Store for merging

            # If we have all 3 recordings, merge them
            if len(RECORDING_LIST) == 3:
                merge_recordings()
        else:
            print(f"❌ Failed to download recording: {response.status_code} - {response.text}")

    except Exception as e:
        print(f"❌ Error while downloading the recording: {str(e)}")

if __name__ == "__main__":
    app.run(port=5000, debug=True)  # ✅ Run Flask server on port 8000
