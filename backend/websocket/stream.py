import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from backend.services.vad import AudioVADDetector
from backend.services.stt import STTService
from backend.services.tts import TTSService
from backend.agents.booking_agent import ClinicalBookingAgent

router = APIRouter()

# Instantiate services
stt_service = STTService()
tts_service = TTSService()
agent_orchestrator = ClinicalBookingAgent()

# Outbound audio chunk size for streaming (e.g. ~4KB chunks)
AUDIO_STREAM_CHUNK_SIZE = 4096

@router.websocket("/ws/stream/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str, phone: str = "9999999999"):
    """Accepts bidirectional, low-latency WebSocket streams for voice conversations."""
    await websocket.accept()
    print(f"WebSocket voice session connected: {session_id} (Phone: {phone})")

    # VAD detector for 16-bit 16kHz PCM
    vad_detector = AudioVADDetector(
        sample_rate=16000,
        chunk_size=512,
        energy_threshold=0.012,
        silence_duration_ms=800
    )

    # Maintain a reference to the current active TTS play task to support barge-in interruption
    active_tts_task: Optional[asyncio.Task] = None

    async def speak_response(text: str, language: str):
        """Asynchronously synthesizes and streams voice audio back to the client in chunks."""
        try:
            print(f"Starting TTS Synthesis for: '{text}' ({language})")
            audio_bytes = await tts_service.synthesize(text, language)
            
            if not audio_bytes:
                return

            # Stream audio buffer in small segments to enable streaming playback on frontend
            idx = 0
            while idx < len(audio_bytes):
                chunk = audio_bytes[idx : idx + AUDIO_STREAM_CHUNK_SIZE]
                # Send raw binary audio chunk
                await websocket.send_bytes(chunk)
                idx += AUDIO_STREAM_CHUNK_SIZE
                # Minor yield to allow event loop cooperative multitasking
                await asyncio.sleep(0.01)
                
            # Send completion signal
            await websocket.send_json({"type": "audio_complete"})
            print("TTS synthesis streaming completed.")
        except asyncio.CancelledError:
            print("Active TTS synthesis cancelled by user barge-in.")
        except Exception as e:
            print(f"Error in TTS streaming: {e}")

    try:
        # Send initial warm welcome to trigger first interaction
        welcome_text = "Hello! I am Aura, your clinical assistant. How can I help you today?"
        await websocket.send_json({
            "type": "transcript",
            "user_text": "",
            "agent_text": welcome_text,
            "reasoning": "Initial welcome greeting.",
            "step_logs": ["Init"]
        })
        active_tts_task = asyncio.create_task(speak_response(welcome_text, "en"))

        while True:
            # Receive binary audio or control events
            message = await websocket.receive()
            
            # 1. Handle JSON Text Events (Control signals)
            if "text" in message:
                try:
                    event = json.loads(message["text"])
                    if event.get("type") == "interrupt":
                        print("Barge-in signal received: interrupting assistant playback.")
                        if active_tts_task and not active_tts_task.done():
                            active_tts_task.cancel()
                            active_tts_task = None
                            # Acknowledge interrupt back to client
                            await websocket.send_json({"type": "interrupted"})
                except json.JSONDecodeError:
                    pass
                continue

            # 2. Handle Binary Audio Input
            if "bytes" in message:
                pcm_data = message["bytes"]
                
                # Pass chunk to Voice Activity Detector
                is_final, speech_audio = vad_detector.process_pcm_chunk(pcm_data)

                # Check for VAD Speech overlap (If client starts speaking while TTS task is running)
                # This acts as an immediate auto-barge-in trigger
                if active_tts_task and not active_tts_task.done() and vad_detector.speech_started:
                    print("User audio overlap detected: Auto-cancelling assistant speech.")
                    active_tts_task.cancel()
                    active_tts_task = None
                    await websocket.send_json({"type": "interrupted"})
                
                if is_final and len(speech_audio) > 0:
                    print(f"Speech final segment captured ({len(speech_audio)} bytes). Processing STT...")
                    
                    # Notify UI that processing has begun
                    await websocket.send_json({"type": "processing"})
                    
                    # Asynchronously transcribe audio
                    transcript = await asyncio.to_thread(stt_service.transcribe, speech_audio)
                    print(f"STT Transcript: '{transcript}'")
                    
                    if not transcript.strip() or len(transcript.strip()) < 2:
                        print("Transcript empty or too short. Ignoring.")
                        await websocket.send_json({"type": "idle"})
                        continue
                    
                    # Execute LangGraph clinical reasoning cycle
                    agent_result = await asyncio.to_thread(
                        agent_orchestrator.run_cycle,
                        session_id=session_id,
                        user_input=transcript,
                        phone_number=phone
                    )
                    
                    # Send response transcript payload back to Next.js
                    await websocket.send_json({
                        "type": "transcript",
                        "user_text": transcript,
                        "agent_text": agent_result["response_text"],
                        "reasoning": agent_result["reasoning"],
                        "step_logs": agent_result["step_logs"]
                    })
                    
                    # Synthesize and stream voice audio
                    active_tts_task = asyncio.create_task(
                        speak_response(
                            agent_result["response_text"],
                            agent_result["language"]
                        )
                    )

    except WebSocketDisconnect:
        print(f"WebSocket session disconnected: {session_id}")
    except Exception as e:
        print(f"WebSocket stream error: {e}")
    finally:
        # Guarantee cancellation of any active speaking thread upon session teardown
        if active_tts_task and not active_tts_task.done():
            active_tts_task.cancel()
