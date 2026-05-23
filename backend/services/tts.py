import os
import asyncio
from dotenv import load_dotenv
import edge_tts

load_dotenv()

# Select high-fidelity neural voices for our clinical agent
VOICE_MAPPING = {
    "en": "en-IN-NeerjaExpressiveNeural",  # English (India) expressive neural voice
    "hi": "hi-IN-MadhurNeural",            # Hindi (India) warm male neural voice
    "ta": "ta-IN-PallaviNeural"            # Tamil (India) clear female neural voice
}

class TTSService:
    """Provides advanced neural text-to-speech synthesis.
    
    Supports both local Coqui TTS models and Microsoft Edge Neural TTS engines for 
    low-latency, production-quality, multilingual speech synthesis.
    """
    def __init__(self):
        self.coqui_loaded = False
        self.coqui_engine = None
        self.edge_tts_blocked = False

        if os.getenv("USE_LOCAL_TTS") == "True":
            try:
                # Optional Coqui TTS initialization if local libraries are built
                from TTS.api import TTS
                print("Loading local Coqui TTS model...")
                model_name = os.getenv("TTS_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
                self.coqui_engine = TTS(model_name).to("cpu")
                self.coqui_loaded = True
                print("Coqui TTS loaded successfully.")
            except Exception as e:
                print(f"Failed to initialize local Coqui TTS. Defaulting to Edge Neural TTS: {e}")

    async def synthesize(self, text: str, language: str = "en") -> bytes:
        """Synthesizes text into audio binary stream in the requested language.
        
        Args:
            text: The text to speak.
            language: Target language ('en', 'hi', 'ta').
            
        Returns:
            bytes: Audio file data (MP3 or WAV).
        """
        if not text:
            return b""

        # Normalize language code
        lang_code = language.lower()[:2]
        voice = VOICE_MAPPING.get(lang_code, VOICE_MAPPING["en"])

        # Try local Coqui TTS if configured
        if self.coqui_loaded and self.coqui_engine:
            try:
                # Synthesize locally to temporary file and read bytes
                temp_file = "temp_voice.wav"
                self.coqui_engine.tts_to_file(
                    text=text, 
                    file_path=temp_file, 
                    speaker=self.coqui_engine.speakers[0] if self.coqui_engine.speakers else None,
                    language=lang_code
                )
                with open(temp_file, "rb") as f:
                    audio_bytes = f.read()
                os.remove(temp_file)
                return audio_bytes
            except Exception as e:
                print(f"Local Coqui TTS synthesis failed, falling back: {e}")

        # High-Performance Neural TTS Fallback: Microsoft Edge TTS API (Free-tier)
        if not self.edge_tts_blocked:
            try:
                # We use edge-tts to generate a highly realistic neural stream
                communicate = edge_tts.Communicate(text, voice)
                audio_io = io_bytes = bytearray()
                
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_io.extend(chunk["data"])
                        
                return bytes(audio_io)
            except Exception as e:
                print(f"Edge TTS Synthesis failed (Setting block bypass flag): {e}")
                self.edge_tts_blocked = True
        else:
            print("Edge TTS is marked as blocked. Bypassing directly to gTTS fallback.")
            
        # Resilient basic fallback using gTTS in case network limits are reached
        try:
            from gtts import gTTS
            import io
            tts = gTTS(text=text, lang=lang_code, slow=False)
            fp = io.BytesIO()
            tts.write_to_fp(fp)
            return fp.getvalue()
        except Exception as gtts_e:
            print(f"All TTS services failed: {gtts_e}")
            return b""
