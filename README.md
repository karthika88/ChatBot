# 🤖 Automatic Interview System with Resume Scoring, Scheduling, and Voice Interviews

This project is a fully-automated interview platform that:
- Scores uploaded resumes
- Schedules interviews through Google Calendar
- Triggers automated Telnyx voice calls for interviews
- Tracks interview status via a user-friendly UI

---

## 🚀 Features

- **Resume Upload and Scoring**: Automatically evaluates resumes based on job descriptions using NLP techniques.
- **Google Calendar Integration**: Schedules interviews and sends calendar invites to candidates.
- **Telnyx Voice API**: Conducts automated interview calls with pre-defined questions.
- **MongoDB Candidate Tracking**: Stores candidate details, application status, and interview results.
- **Real-time Status Updates**: Provides a user-friendly dashboard to track interview progress.

---

## 🛠️ Setup Instructions

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/automatic-interview-system.git
cd automatic-interview-system
```

### 2. Install Dependencies

Install the required Python packages:

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Update the `.env` files in the root and `app/` directories with your credentials:

- MongoDB URI
- Telnyx API Key and Connection ID
- Google OAuth credentials
- OpenAI API Key (if applicable)

Refer to the provided `.env` files for the required variables.

### 4. Set Up Webhook URL

The Telnyx API requires a publicly accessible webhook URL to send call events (e.g., call start, recording stop). Follow these steps to set up the webhook:

#### a. Use a Public URL for Local Development

If you're running the application locally, you can use a tool like [ngrok](https://ngrok.com/) to expose your local server to the internet.

1. Install ngrok:
   ```bash
   choco install ngrok
   ```
   *(For Windows users, ensure Chocolatey is installed. For other platforms, refer to the ngrok documentation.)*

2. Start ngrok on port 8000 (the default port for the FastAPI server):
   ```bash
   ngrok http 8000
   ```

3. Copy the generated public URL (e.g., `https://<random-string>.ngrok.io`).

#### b. Configure the Webhook in Telnyx

1. Log in to your Telnyx account.
2. Navigate to **Call Control Applications** in the Telnyx dashboard.
3. Create or edit an application and set the **Webhook URL** to:
   ```
   https://<your-public-url>/webhook/telnyx
   ```
4. Save the changes.

#### c. Update the `.env` File

Add the public URL to your `.env` file:
```
WEBHOOK_URL=https://<your-public-url>/webhook/telnyx
```

### 5. Start the Application

1. Start the FastAPI server:
   ```bash
   uvicorn app.main:app --reload
   ```

2. Access the application at `http://localhost:8000`.

---

## 📂 Project Structure and Workflow

### 1. **Frontend (User Interface)**

- **File**: [`templates/index.html`](ChatBot/templates/index.html)
- **Description**: The main user interface where candidates can:
  - Upload their resumes.
  - Check their interview status.
  - Schedule interviews if shortlisted.
- **Static Assets**:
  - [`static/style.css`](ChatBot/static/style.css): Custom styles for the UI.
  - [`static/css/style.css`](ChatBot/static/css/style.css): Additional styles for specific components.

### 2. **Resume Upload and Scoring**

- **File**: [`app/resume_selection.py`](ChatBot/app/resume_selection.py)
- **Description**:
  - Handles resume uploads via the `/upload_resume/` endpoint.
  - Extracts text from PDF/DOCX files.
  - Uses the `SentenceTransformer` model to calculate similarity between the resume and job descriptions.
  - Stores candidate details and match scores in MongoDB.
- **Job Descriptions**: Defined in the `JOB_DESCRIPTIONS` dictionary within the file.

### 3. **Database Integration**

- **File**: [`app/database.py`](ChatBot/app/database.py)
- **Description**:
  - Connects to MongoDB to store and retrieve candidate data.
  - Provides utility functions for updating candidate status and fetching interview results.

### 4. **Interview Scheduling**

- **File**: [`app/google_calendar.py`](ChatBot/app/google_calendar.py)
- **Description**:
  - Integrates with Google Calendar to schedule interviews.
  - Creates calendar events with candidate details and interview times.
  - Fetches available time slots for scheduling.

### 5. **Interview Workflow**

#### a. **Telnyx Call Handling**

- **File**: [`app/routes/telnyx_call.py`](ChatBot/app/routes/telnyx_call.py)
- **Description**:
  - Initiates calls to candidates using the Telnyx API.
  - Plays pre-recorded questions and records candidate responses.
  - Handles call events such as recording start/stop and call completion.

#### b. **Webhook Handling**

- **File**: [`app/webhook_handler.py`](ChatBot/app/webhook_handler.py)
- **Description**:
  - Processes incoming webhook events from Telnyx.
  - Downloads and merges call recordings.
  - Saves recordings for further processing.

#### c. **Interview Monitoring**

- **File**: [`app/interview_bridge.py`](ChatBot/app/interview_bridge.py)
- **Description**:
  - Monitors Google Calendar for upcoming interviews.
  - Triggers Telnyx calls at the scheduled time.
  - Processes candidate responses and updates their status in MongoDB.

### 6. **Response Evaluation**

- **File**: [`app/evaluator.py`](ChatBot/app/evaluator.py)
- **Description**:
  - Converts audio recordings to text using Whisper or Google Speech Recognition.
  - Evaluates candidate responses using cosine similarity.
  - Categorizes responses as "Excellent," "Good," or "Below Average."

### 7. **API Endpoints**

#### a. **Interview Routes**

- **File**: [`app/routes/interview_routes.py`](ChatBot/app/routes/interview_routes.py)
- **Endpoints**:
  - `/api/available-slots/{candidate_id}`: Fetches available interview slots.
  - `/api/schedule-interview`: Schedules an interview for a candidate.

#### b. **Interview Result**

- **File**: [`app/main.py`](ChatBot/app/main.py)
- **Endpoint**:
  - `/get_interview_result/`: Fetches the interview result for a given candidate ID.

### 8. **Questions**

- **File**: [`app/questions.py`](ChatBot/app/questions.py)
- **Description**: Contains the list of pre-defined interview questions.

---

## 🔄 Workflow Overview

1. **Resume Upload**:
   - Candidates upload their resumes via the UI.
   - The system evaluates the resume and calculates a match score.
   - If the score is above the threshold, the candidate is shortlisted for an interview.

2. **Interview Scheduling**:
   - Shortlisted candidates can select an available time slot.
   - The system schedules the interview in Google Calendar and sends an invite.

3. **Automated Interview**:
   - At the scheduled time, the system triggers a Telnyx call.
   - The candidate answers pre-defined questions, and their responses are recorded.

4. **Response Evaluation**:
   - The system transcribes the recordings and evaluates the responses.
   - Candidates are categorized based on their performance.

5. **Result Tracking**:
   - Candidates can check their interview status via the UI.

---

## 🛡️ Security

- Sensitive credentials are stored in `.env` files and should not be hardcoded.
- Ensure proper access control for the MongoDB database and API keys.

---
