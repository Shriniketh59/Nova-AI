"""
Local STT — faster-whisper based Speech-to-Text.

Uses the CTranslate2-accelerated Whisper model running entirely locally.
No cloud API. No browser Web Speech API.

Model: "base.en" (~150MB, downloads once to ~/.cache/huggingface/)
       Falls back to "tiny.en" (~40MB) if base.en unavailable.

Usage:
    from server.app.voice.local_stt import LocalSTT
    stt = LocalSTT.get_instance()
    transcript = stt.transcribe_bytes(wav_bytes)
"""
import io
import logging
import threading
import wave
from typing import Optional

import numpy as np

logger = logging.getLogger("nova.stt")

# Whisper model size — base.en good balance of speed/accuracy on CPU
# tiny.en is faster but less accurate; small.en needs more RAM
STT_MODEL_SIZE = "base.en"
STT_DEVICE = "cpu"
STT_COMPUTE_TYPE = "int8"  # int8 quantization — faster on CPU, lower RAM


class LocalSTT:
    """
    Singleton wrapper around faster-whisper WhisperModel.
    The model is loaded once and reused across all requests.
    """
    _instance: Optional["LocalSTT"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._model = None
        self._model_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "LocalSTT":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_model(self):
        """Load faster-whisper model (lazy, thread-safe)."""
        if self._model is not None:
            return
        with self._model_lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel
                logger.info(f"Loading faster-whisper model: {STT_MODEL_SIZE}")
                self._model = WhisperModel(
                    STT_MODEL_SIZE,
                    device=STT_DEVICE,
                    compute_type=STT_COMPUTE_TYPE,
                )
                logger.info("faster-whisper model loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load faster-whisper model: {e}")
                raise

    def transcribe_bytes(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """
        Transcribe raw PCM or WAV bytes to text.

        Parameters
        ----------
        audio_bytes : bytes
            Raw 16-bit PCM (int16) bytes at sample_rate Hz, or a WAV file.
        sample_rate : int
            Sample rate of the audio (default 16000 Hz).

        Returns
        -------
        str
            Transcribed text, or empty string on failure.
        """
        self._load_model()

        try:
            # Detect if this is WAV-wrapped or raw PCM
            if audio_bytes[:4] == b"RIFF":
                # WAV file — extract PCM
                with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                    sample_rate = wf.getframerate()
                    pcm_bytes = wf.readframes(wf.getnframes())
            else:
                pcm_bytes = audio_bytes

            # Convert bytes → float32 array (faster-whisper expects float32, -1..1)
            pcm_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
            audio_float32 = pcm_int16.astype(np.float32) / 32768.0

            # Transcribe
            segments, _info = self._model.transcribe(
                audio_float32,
                language="en",
                beam_size=3,
                vad_filter=True,           # skip silence
                vad_parameters={"min_silence_duration_ms": 300},
            )

            transcript = " ".join(seg.text.strip() for seg in segments).strip()
            logger.info(f"STT transcript: {transcript[:80]!r}")
            return transcript

        except Exception as e:
            logger.error(f"STT transcription failed: {e}")
            return ""

    def transcribe_file(self, filepath: str) -> str:
        """Transcribe an audio file (WAV/MP3/etc.) given a path."""
        self._load_model()
        try:
            segments, _info = self._model.transcribe(
                filepath,
                language="en",
                beam_size=3,
                vad_filter=True,
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
        except Exception as e:
            logger.error(f"STT file transcription failed: {e}")
            return ""


# Singleton accessor
def get_stt() -> LocalSTT:
    return LocalSTT.get_instance()
