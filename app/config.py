import os
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env file

TELNYX_API_KEY = os.getenv("TELNYX_API_KEY")
TELNYX_CONNECTION_ID = os.getenv("TELNYX_CONNECTION_ID")
TELNYX_PHONE_NUMBER = os.getenv("TELNYX_PHONE_NUMBER")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Debugging print statements
print(f"🔑 TELNYX_API_KEY: {TELNYX_API_KEY[:10]}...")  # Print partial key for security
print(f"📞 TELNYX_PHONE_NUMBER: {TELNYX_PHONE_NUMBER}")
print(f"🌐 WEBHOOK_URL: {WEBHOOK_URL}")


