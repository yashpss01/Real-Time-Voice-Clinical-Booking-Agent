import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

try:
    print("Testing gemini-2.5-flash...")
    model = genai.GenerativeModel("gemini-2.5-flash")
    resp = model.generate_content("Hello! What is your name?")
    print("Response:", resp.text.strip())
except Exception as e:
    print("Failed gemini-2.5-flash:", e)
