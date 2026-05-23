import numpy as np

class AudioVADDetector:
    """A lightweight, low-latency, energy-based Voice Activity Detector (VAD).
    
    Segments continuous PCM audio streams into distinct utterance segments based on 
    signal amplitude, moving energy thresholds, and silence windows.
    """
    def __init__(self, sample_rate: int = 16000, chunk_size: int = 512, 
                 energy_threshold: float = 0.015, silence_duration_ms: int = 800):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.energy_threshold = energy_threshold
        
        # Calculate samples representing trailing silence window
        self.silence_limit = int((silence_duration_ms / 1000.0) * sample_rate)
        
        self.audio_buffer = bytearray()
        self.speech_started = False
        self.silence_samples_count = 0
        self.active_utterance_data = []
        self.speech_chunks_count = 0

    def process_pcm_chunk(self, raw_pcm_bytes: bytes) -> tuple[bool, bytes]:
        """Processes a continuous binary block of 16-bit 16kHz mono PCM.
        
        Returns:
            Tuple[bool, bytes]: (is_speech_final, completed_utterance_audio_bytes)
        """
        self.audio_buffer.extend(raw_pcm_bytes)
        
        # Check if we have at least one complete chunk to analyze
        bytes_per_sample = 2  # 16-bit
        chunk_bytes_needed = self.chunk_size * bytes_per_sample
        
        is_speech_final = False
        completed_audio = b""
        
        while len(self.audio_buffer) >= chunk_bytes_needed:
            # Extract current chunk
            chunk_data = self.audio_buffer[:chunk_bytes_needed]
            del self.audio_buffer[:chunk_bytes_needed]
            
            # Convert to normalized float32 array to analyze signal energy
            audio_samples = np.frombuffer(chunk_data, dtype=np.int16).astype(np.float32) / 32768.0
            
            # Compute Root-Mean-Square (RMS) signal energy
            rms_energy = np.sqrt(np.mean(audio_samples ** 2)) if len(audio_samples) > 0 else 0
            
            if rms_energy > self.energy_threshold:
                # Speech onset detected
                if not self.speech_started:
                    self.speech_started = True
                    self.active_utterance_data = []
                    self.speech_chunks_count = 0
                self.silence_samples_count = 0
                self.active_utterance_data.append(chunk_data)
                self.speech_chunks_count += 1
            else:
                if self.speech_started:
                    # Accumulate silence samples while speech is ongoing
                    self.silence_samples_count += self.chunk_size
                    self.active_utterance_data.append(chunk_data)
                    
                    # If silence duration exceeds limit, trigger voice segment completion
                    if self.silence_samples_count >= self.silence_limit:
                        # Only finalize if the total active speech chunks exceed our noise filter limit (e.g. >= 3 chunks or ~96ms)
                        if self.speech_chunks_count >= 3:
                            is_speech_final = True
                            completed_audio = b"".join(self.active_utterance_data)
                        else:
                            is_speech_final = False
                            completed_audio = b""
                        
                        # Reset VAD state machine
                        self.speech_started = False
                        self.silence_samples_count = 0
                        self.active_utterance_data = []
                        self.speech_chunks_count = 0
                        break
        
        return is_speech_final, completed_audio
