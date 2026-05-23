import os
import io
import wave
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

class STTService:
    """Provides speech-to-text transcription services.
    
    Supports both local Faster Whisper inference and high-performance, low-latency 
    Gemini Multimodal Speech Transcription.
    """
    def __init__(self):
        self.model_loaded = False
        self.whisper_model = None
        
        # Load local Faster Whisper only if requested and model size is specified
        whisper_model_size = os.getenv("WHISPER_MODEL_SIZE", "base")
        if os.getenv("USE_LOCAL_STT") == "True":
            try:
                from faster_whisper import WhisperModel
                print(f"Loading local Faster Whisper model: {whisper_model_size}...")
                # Run on CPU by default with float32 or int8
                self.whisper_model = WhisperModel(whisper_model_size, device="cpu", compute_type="int8")
                self.model_loaded = True
                print("Faster Whisper model loaded successfully.")
            except Exception as e:
                print(f"Failed to load local Faster Whisper. Falling back to Gemini Multimodal STT: {e}")

    def convert_pcm_to_wav(self, pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
        """Converts raw 16kHz PCM bytes to standard RIFF-WAV binary formats."""
        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)   # 16-bit PCM (2 bytes)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return wav_io.getvalue()

    def transcribe(self, pcm_bytes: bytes, sample_rate: int = 16000) -> str:
        """Transcribes raw PCM audio bytes to text string."""
        if not pcm_bytes:
            return ""

        # If local Faster Whisper is loaded, run local inference
        if self.model_loaded and self.whisper_model:
            try:
                # Faster Whisper needs a file path or file-like object
                wav_data = self.convert_pcm_to_wav(pcm_bytes, sample_rate)
                wav_io = io.BytesIO(wav_data)
                segments, info = self.whisper_model.transcribe(wav_io, beam_size=5)
                transcript = " ".join([segment.text for segment in segments])
                return transcript.strip()
            except Exception as e:
                print(f"Local Faster Whisper transcription failed, falling back to Gemini API: {e}")

        # Primary High-Performance Fallback: Gemini Multimodal Audio API
        # Sends high-fidelity 16kHz WAV directly to Gemini Flash for sub-150ms transcription
        try:
            import time
            wav_bytes = self.convert_pcm_to_wav(pcm_bytes, sample_rate)
            
            # Prepare multimodal request using Gemini Flash
            model = genai.GenerativeModel("gemini-2.5-flash-lite")
            
            prompt = """
            You are a professional audio transcriber. Transcribe the following speech audio exactly as it is spoken.
            Do not translate it. Keep it in the native language it was spoken (English, Hindi, or Tamil).
            Do not add any preamble, explanations, or commentary. Output ONLY the transcription.
            """
            
            retries = 5
            delay = 2
            for i in range(retries):
                try:
                    response = model.generate_content([
                        prompt,
                        {
                            "mime_type": "audio/wav",
                            "data": wav_bytes
                        }
                    ])
                    try:
                        return response.text.strip()
                    except (ValueError, AttributeError) as ve:
                        print(f"Gemini STT returned no valid text parts (possibly blocked or safety trigger): {ve}")
                        return ""
                except Exception as e:
                    err_msg = str(e)
                    if ("429" in err_msg or "quota" in err_msg.lower() or "limit" in err_msg.lower()) and i < retries - 1:
                        sleep_time = delay * (2 ** i)
                        print(f"Gemini STT API rate limit hit (429). Retrying in {sleep_time}s... (Attempt {i+1}/{retries})")
                        time.sleep(sleep_time)
                    else:
                        raise e
        except Exception as e:
            print(f"Gemini Multimodal Audio Transcription failed: {e}")
            return ""
