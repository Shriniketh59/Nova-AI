"""
Local TTS — pyttsx3 + espeak-ng Text-to-Speech.

Fully local, no cloud API, no browser SpeechSynthesis.
espeak-ng library is installed on this system (/usr/lib/x86_64-linux-gnu/libespeak-ng.so.1).
pyttsx3 wraps it for Python.

The TTS engine is run in a background thread pool to avoid blocking the async event loop.

Usage (async):
    from server.app.voice.local_tts import LocalTTS
    tts = LocalTTS.get_instance()
    audio_bytes = await tts.synthesize("Hello, how can I help you?")
    # audio_bytes is WAV data or empty bytes on error
"""
import asyncio
import io
import logging
import os
import tempfile
import threading
import wave
from typing import Optional

logger = logging.getLogger("nova.tts")

# Default voice — "English (Great Britain)" from espeak-ng
# Can be overridden with TTS_VOICE env var
TTS_VOICE_ID = os.environ.get("TTS_VOICE", "gmw/en")
TTS_RATE = int(os.environ.get("TTS_RATE", "165"))   # words per minute
TTS_VOLUME = float(os.environ.get("TTS_VOLUME", "1.0"))


class LocalTTS:
    """
    Singleton wrapper around pyttsx3 TTS engine (espeak-ng backend).
    Engine runs in a dedicated thread to avoid event loop blocking.
    """
    _instance: Optional["LocalTTS"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._engine = None
        self._engine_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "LocalTTS":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load_engine(self):
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

                # Select English voice
                voices = engine.getProperty("voices")
                selected = None
                for v in voices:
                    if TTS_VOICE_ID in (v.id or ""):
                        selected = v
                        break
                if not selected:
                    # Fallback: first English voice
                    for v in voices:
                        if "en" in (v.id or "").lower():
                            selected = v
                            break
                if selected:
                    engine.setProperty("voice", selected.id)
                    logger.info(f"TTS voice: {selected.name} ({selected.id})")
                else:
                    logger.warning("No English TTS voice found, using default.")

                self._engine = engine
                logger.info("pyttsx3 TTS engine loaded.")
            except Exception as e:
                logger.error(f"Failed to load TTS engine: {e}")
                raise

    def _synthesize_blocking(self, text: str) -> bytes:
        """
        Blocking call: synthesize text → WAV bytes.
        Saves to a temp file because pyttsx3's save_to_file is the most
        reliable cross-driver approach.
        """
        self._load_engine()
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
            logger.error(f"TTS synthesis failed: {e}")
            return b""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    async def synthesize(self, text: str) -> bytes:
        """
        Async wrapper — runs pyttsx3 synthesis in thread pool.
        Returns WAV bytes or b"" on error.
        """
        if not text or not text.strip():
            return b""
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, self._synthesize_blocking, text)
        except Exception as e:
            logger.error(f"TTS async synthesis failed: {e}")
            return b""

    def speak_blocking(self, text: str) -> None:
        """Speak text directly (blocking, for non-async contexts)."""
        self._load_engine()
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
