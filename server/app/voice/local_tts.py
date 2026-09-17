"""
Local TTS — Crystal-Clear Neural Text-to-Speech with pyttsx3 fallback.

Upgrades voice clarity to state-of-the-art neural speech (edge-tts):
- Studio-quality, natural prosody, crisp articulation without metallic distortion
- Configurable voices (default: en-US-GuyNeural or en-US-AriaNeural)
- Automatic fallback to pyttsx3/espeak-ng if network is offline
"""
import asyncio
import io
import logging
import os
import tempfile
import threading
from typing import Optional, Tuple

logger = logging.getLogger("nova.tts")

# Preferred neural voice for crystal-clear, professional Siri-like speech
TTS_VOICE_ID = os.environ.get("TTS_VOICE", "en-US-AvaNeural")
TTS_RATE = int(os.environ.get("TTS_RATE", "165"))
TTS_VOLUME = float(os.environ.get("TTS_VOLUME", "1.0"))

SUPPORTED_VOICES = {
    "siri_ava": "en-US-AvaNeural",
    "siri_jenny": "en-US-JennyNeural",
    "siri_aria": "en-US-AriaNeural",
    "siri_andrew": "en-US-AndrewNeural",
    "siri_sonia": "en-GB-SoniaNeural",
}


class LocalTTS:
    """
    Singleton TTS engine prioritizing crystal-clear neural speech
    with offline pyttsx3 fallback.
    """
    _instance: Optional["LocalTTS"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._engine = None
        self._engine_lock = threading.Lock()
        self._has_edge_tts = True

    @classmethod
    def get_instance(cls) -> "LocalTTS":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_pyttsx3_engine(self):
        if self._engine is not None:
            return
        with self._engine_lock:
            if self._engine is not None:
                return
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", TTS_RATE)
                engine.setProperty("volume", TTS_VOLUME)

                voices = engine.getProperty("voices")
                selected = None
                for v in voices:
                    if "en" in (v.id or "").lower():
                        selected = v
                        break
                if selected:
                    engine.setProperty("voice", selected.id)
                self._engine = engine
                logger.info("pyttsx3 fallback TTS engine loaded.")
            except Exception as e:
                logger.error(f"Failed to load pyttsx3 engine: {e}")
                self._engine = None

    async def _synthesize_neural(self, text: str, voice: Optional[str] = None) -> Optional[bytes]:
        """Synthesize text using edge-tts for crystal-clear neural speech."""
        try:
            import edge_tts
            target_voice = voice or TTS_VOICE_ID
            if target_voice in SUPPORTED_VOICES:
                target_voice = SUPPORTED_VOICES[target_voice]
            communicate = edge_tts.Communicate(text, target_voice, rate="+0%", pitch="+0Hz")
            chunks = []
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
            if chunks:
                return b"".join(chunks)
        except Exception as e:
            logger.warn(f"Neural TTS failed ({e}), falling back to pyttsx3.")
        return None

    def _synthesize_pyttsx3_blocking(self, text: str) -> bytes:
        """Blocking pyttsx3 synthesis as an offline fallback."""
        self._load_pyttsx3_engine()
        if not self._engine:
            return b""
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            self._engine.save_to_file(text, tmp_path)
            self._engine.runAndWait()

            if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                with open(tmp_path, "rb") as f:
                    return f.read()
            return b""
        except Exception as e:
            logger.error(f"pyttsx3 fallback failed: {e}")
            return b""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    async def synthesize_with_mime(self, text: str, voice: Optional[str] = None) -> Tuple[bytes, str]:
        """
        Synthesize text to high-clarity audio bytes and return (audio_bytes, mime_type).
        Supports custom Siri neural voices with offline pyttsx3 fallback.
        """
        if not text or not text.strip():
            return b"", "audio/mpeg"

        # 1. Try crystal-clear neural voice
        if self._has_edge_tts:
            neural_bytes = await self._synthesize_neural(text, voice=voice)
            if neural_bytes:
                return neural_bytes, "audio/mpeg"

        # 2. Fall back to pyttsx3 WAV
        loop = asyncio.get_running_loop()
        wav_bytes = await loop.run_in_executor(None, self._synthesize_pyttsx3_blocking, text)
        return wav_bytes, "audio/wav"

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        """Async synthesis returning audio bytes."""
        audio, _ = await self.synthesize_with_mime(text, voice=voice)
        return audio

    def speak_blocking(self, text: str) -> None:
        """Speak text directly (blocking, for non-async contexts)."""
        self._load_pyttsx3_engine()
        if self._engine:
            try:
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as e:
                logger.error(f"TTS speak failed: {e}")

    def stop(self) -> None:
        """Stop any in-progress speech immediately."""
        if self._engine:
            try:
                self._engine.stop()
            except Exception:
                pass


def get_tts() -> LocalTTS:
    return LocalTTS.get_instance()
