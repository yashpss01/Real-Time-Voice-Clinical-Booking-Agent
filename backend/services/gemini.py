import os
import json
import time
from typing import Dict, Any, List, Optional
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is not set")

genai.configure(api_key=GEMINI_API_KEY)

class GeminiService:
    """Orchestrates structured entity parsing, multi-turn clinical reasoning, 

    language detection, and localized dynamic translation using Google Gemini 3.5 Flash.
    """
    def __init__(self, model_name: str = "gemini-2.5-flash-lite"):
        self.model_name = model_name
        self.model = genai.GenerativeModel(model_name)

    def _generate_with_retry(self, contents, generation_config=None, retries=5, delay=2):
        """Generates content with automatic exponential backoff for 429 quota errors."""
        for i in range(retries):
            try:
                if generation_config:
                    return self.model.generate_content(contents, generation_config=generation_config)
                else:
                    return self.model.generate_content(contents)
            except Exception as e:
                err_msg = str(e)
                if ("429" in err_msg or "quota" in err_msg.lower() or "limit" in err_msg.lower()) and i < retries - 1:
                    sleep_time = delay * (2 ** i)
                    print(f"Gemini API rate limit hit (429). Retrying in {sleep_time}s... (Attempt {i+1}/{retries})")
                    time.sleep(sleep_time)
                else:
                    raise e

    def detect_language(self, text: str) -> str:
        """Auto-detects language of patient speech. Returns 'en', 'hi', or 'ta'."""
        if not text.strip():
            return "en"
            
        prompt = f"""
        Analyze the following text and detect if it is spoken in English, Hindi, or Tamil.
        Return ONLY the two-letter language code:
        - 'en' for English
        - 'hi' for Hindi (includes Hinglish or transliterated Hindi)
        - 'ta' for Tamil (includes Tanglish or transliterated Tamil)
        
        If it's ambiguous or contains multiple languages, default to the dominant one, or 'en'.
        Output ONLY the code (e.g. 'en', 'hi', 'ta'). Do not add any punctuation or comments.
        
        Text to analyze:
        "{text}"
        """
        try:
            response = self._generate_with_retry(prompt)
            code = response.text.strip().lower()
            return code if code in ["en", "hi", "ta"] else "en"
        except Exception as e:
            print(f"Language detection failed: {e}")
            return "en"

    def parse_entities(self, text: str, history_summary: str = "") -> Dict[str, Any]:
        """Extracts conversational intent, scheduling entities, and confirmation flags.
        
        Returns a structured dictionary of clinical entities.
        """
        # Formulate instructions for structured JSON output
        prompt = f"""
        You are a clinical database parser. Extract intent and scheduling entities from the User Utterance.
        You must output a raw valid JSON object. Do not include any markdown fences (like ```json).
        
        Here is the conversation history context:
        {history_summary}
        
        User Utterance:
        "{text}"
        
        Your JSON output MUST match the following keys:
        {{
            "intent": "BOOKING" | "RESCHEDULING" | "CANCELLATION" | "CONFIRMATION" | "GENERAL_QUERY" | null,
            "specialization": "General Medicine" | "Pediatrics" | "Orthopedics" | null,
            "doctor_name": string (e.g. "Dr. Priya Ramachandran") | null,
            "date": string in YYYY-MM-DD format (representing requested date, relative to today's date of 2026-05-22) | null,
            "time": string (e.g. "10:30", "15:00", "evening", "morning") | null,
            "confirm": true | false | null (whether user is saying 'yes', 'confirm', 'sure' or 'no', 'cancel' to a pending slot confirmation)
        }}
        
        Rules:
        1. If the user mentions "next week", relative to today (Friday, May 22, 2026), translate to the actual dates (e.g. Monday May 25, 2026).
        2. Set intent to "CONFIRMATION" if the user is explicitly confirming or rejecting a previously proposed slot.
        3. Match doctor names closely to known doctors: Dr. Rajesh Kumar, Dr. Priya Ramachandran, Dr. Anand Iyer, Dr. Sarah Jenkins.
        """
        
        try:
            # Request JSON output configuration
            response = self._generate_with_retry(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            data = json.loads(response.text.strip())
            return data
        except Exception as e:
            print(f"Entity parsing failed: {e}")
            return {
                "intent": None,
                "specialization": None,
                "doctor_name": None,
                "date": None,
                "time": None,
                "confirm": None
            }

    def generate_clinical_response(self, 
                                   user_input: str,
                                   history: List[Dict[str, str]], 
                                   patient_name: str,
                                   state_info: Dict[str, Any]) -> str:
        """Formulates the clinical logic and dialog in English.
        
        The model acts as a direct booking assistant operating on DB state.
        """
        formatted_history = "\n".join([f"{h['role'].capitalize()}: {h['text']}" for h in history[-6:]])
        
        system_prompt = f"""
        You are a highly efficient, empathetic real-time clinical booking AI assistant named 'Aura'.
        You are helping the patient '{patient_name}'.
        Today is Friday, May 22, 2026.
        
        Your objective is to help book, reschedule, or cancel clinical appointments.
        Keep responses concise, clear, and focused on voice dialogue (short sentences, no bullet lists, no asterisks, no bold markdown).
        
        Current Scheduling State context:
        {json.dumps(state_info, indent=2)}
        
        Conversation history:
        {formatted_history}
        
        Latest User Utterance: "{user_input}"
        
        Dialogue Guidelines:
        1. If a slot conflict (double booking) or invalid date occurred, explain it clearly and offer alternative available slots immediately.
        2. If the user request is ambiguous (e.g. "next week in the evening"), ask clarifying questions (e.g. "Which day next week would you prefer?").
        3. When a doctor and slot are found, summarize and ask for confirmation clearly (e.g. "I can book Dr. Priya on Monday, May 25th at 10:00 AM. Should I confirm this?").
        4. If an appointment is confirmed or successfully modified/cancelled, state it clearly.
        5. Speak naturally in conversational English. Do not write lists or paragraphs.
        """
        
        try:
            response = self._generate_with_retry(system_prompt)
            return response.text.strip()
        except Exception as e:
            print(f"Clinical reasoning failed: {e}")
            return "I am sorry, I encountered an issue updating your records. How can I help you right now?"

    def translate_response(self, text: str, target_lang: str) -> str:
        """Translates English reasoning output dynamically to user's preferred language."""
        if not target_lang or target_lang.lower() == "en":
            return text
            
        lang_name = "Hindi" if target_lang.lower() == "hi" else "Tamil"
        
        prompt = f"""
        Translate the following English clinical assistant response into natural, spoken {lang_name}.
        Keep the tone polite, professional, and conversational.
        Do not add any explanations, annotations, or English text unless it's a name (like Dr. Priya) or standard term.
        Output ONLY the translation.
        
        English Text:
        "{text}"
        """
        try:
            response = self._generate_with_retry(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"Translation to {lang_name} failed: {e}")
            return text
