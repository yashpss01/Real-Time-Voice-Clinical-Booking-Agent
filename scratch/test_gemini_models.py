import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
print("API Key loaded:", GEMINI_API_KEY is not None)

genai.configure(api_key=GEMINI_API_KEY)

try:
    print("Listing available models...")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"Model Name: {m.name} | Display Name: {m.display_name}")
except Exception as e:
    print("Error listing models:", e)
