import os
import whisper
import speech_recognition as sr
from pydub import AudioSegment
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pydub.utils import which

# Ensure FFmpeg paths are correctly set
AudioSegment.converter = which("ffmpeg") or "C:/ffmpeg/bin/ffmpeg.exe"
AudioSegment.ffprobe = which("ffprobe") or "C:/ffmpeg/bin/ffprobe.exe"

# Create output directory if it doesn't exist
OUTPUT_DIR = "converted_audio"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def convert_audio_to_wav(input_path):
    """ Converts audio to WAV format, saves in 'converted_audio/' folder. """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"❌ File not found: {input_path}")

    output_wav = os.path.join(OUTPUT_DIR, "output.wav")

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
def transcribe_audio(wav_path, use_whisper=True):
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
def evaluate_response(candidate_response, ideal_response):
    """ Compares candidate's response with ideal answer using cosine similarity. """
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform([candidate_response, ideal_response])
    score = cosine_similarity(tfidf_matrix[0], tfidf_matrix[1])[0][0] * 10  
    return round(score, 2)

### **4️⃣ Categorize Candidate Response**
def categorize_score(score):
    """ Categorizes response based on score. """
    if score >= 8:
        return "Excellent"
    elif score >= 5:
        return "Good"
    else:
        return "Below Average"

### **🏁 Main Function**
def process_candidate_response(audio_file, use_whisper=True):
    """ Full pipeline: Convert → Transcribe → Evaluate → Categorize """

    # Step 1: Convert to WAV
    wav_file = convert_audio_to_wav(audio_file)

    # Step 2: Speech-to-Text
    candidate_response = transcribe_audio(wav_file, use_whisper)
    if not candidate_response:
        return {"error": "Failed to transcribe audio."}

    # Step 3: Evaluate & Categorize
    ideal_response = "I am a highly motivated candidate with experience in Python development and machine learning."
    score = evaluate_response(candidate_response, ideal_response)
    category = categorize_score(score)

    return {
        "transcribed_text": candidate_response,
        "score": score,
        "category": category
    }

### **🎯 Example Usage**
if __name__ == "__main__":
    audio_file = "recordings/final_interview.wav"  # Update this path as needed
    result = process_candidate_response(audio_file, use_whisper=True)
    print("\n🔹 Final Result:", result)
