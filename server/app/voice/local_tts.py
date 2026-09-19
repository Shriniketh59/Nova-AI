"""
Local TTS — 100% offline text-to-speech via pyttsx3.

No external / cloud speech service is used or permitted here. On Linux pyttsx3
drives `espeak-ng`, which must be installed on the host (see the README's
"Voice Setup" section); on macOS it uses NSSpeechSynthesizer and on Windows
SAPI5. Nothing leaves the machine.

Voice selection is automatic and defensive:
  1. If TTS_VOICE_ID is set, that voice id is used verbatim (no auto-detection).
  2. Otherwise the installed voices are scored and the best available English
     voice is chosen, preferring en-GB and preferring male.
  3. If the platform reports NO voices at all, synthesis fails with an explicit,
     inspectable error state (TTSUnavailableError / get_status()) instead of
     crashing the app or silently returning empty audio.
"""
import asyncio
import logging
import os
import tempfile
import threading
from typing import Optional, Tuple

logger = logging.getLogger("nova.tts")

# Explicit override — when set, auto-detection is skipped entirely. Use this on
# hosts where the heuristics below pick a voice you don't want. Discover valid
# ids with:  python -c "import pyttsx3;[print(v.id, v.name) for v in pyttsx3.init().getProperty('voices')]"
TTS_VOICE_ID_OVERRIDE = os.environ.get("TTS_VOICE_ID", "").strip()

TTS_RATE = int(os.environ.get("TTS_RATE", "165"))
TTS_VOLUME = float(os.environ.get("TTS_VOLUME", "1.0"))

# Named presets the API/UI can request. These are *preference hints* resolved
# against whatever voices are actually installed — never hardcoded voice ids
# that may not exist on the host.
#
# (Deliberately no Siri-branded or cloud-neural voice names: this engine is
# espeak-ng/SAPI/NSSpeech, and the product must not imply otherwise.)
SUPPORTED_VOICES = {
    "nova_uk_male":   {"lang": "en-gb", "gender": "male",   "label": "British English (Male)"},
    "nova_uk_female": {"lang": "en-gb", "gender": "female", "label": "British English (Female)"},
    "nova_us_male":   {"lang": "en-us", "gender": "male",   "label": "US English (Male)"},
    "nova_us_female": {"lang": "en-us", "gender": "female", "label": "US English (Female)"},
    "nova_default":   {"lang": "en-gb", "gender": "male",   "label": "Default (British English, Male)"},
}

DEFAULT_VOICE_KEY = "nova_default"


class TTSUnavailableError(RuntimeError):
    """No usable local speech engine/voice is installed on this host."""


# ---------------------------------------------------------------------------
# Voice selection
# ---------------------------------------------------------------------------

_FEMALE_NAME_HINTS = ("female", "+f1", "+f2", "+f3", "+f4", "+f5", "woman", "zira", "samantha", "victoria", "karen")
_MALE_NAME_HINTS = ("male", "+m1", "+m2", "+m3", "+m4", "+m5", "man", "david", "daniel", "alex", "fred")
_GB_HINTS = ("en-gb", "en_gb", "en-uk", "en_uk", "british", "great britain", "united kingdom", "gbr", "rp")
_US_HINTS = ("en-us", "en_us", "american", "united states", "usa")


def _voice_text(voice) -> str:
    """All identifying strings a pyttsx3 Voice exposes, lowercased.

    Attributes differ a lot between drivers (espeak exposes `languages` as a
    list of bytes, SAPI5 exposes none of it), so everything is inspected
    defensively rather than assuming a shape.
    """
    parts = [str(getattr(voice, "id", "") or ""), str(getattr(voice, "name", "") or "")]
    languages = getattr(voice, "languages", None) or []
    if isinstance(languages, (str, bytes)):
        languages = [languages]
    for lang in languages:
        if isinstance(lang, bytes):
            # espeak prefixes a length byte, e.g. b'\x05en-gb'
            parts.append(lang.decode("utf-8", errors="ignore"))
        else:
            parts.append(str(lang))
    return " ".join(parts).lower().replace("_", "-")


def _voice_gender(voice, text: str) -> Optional[str]:
    """Best-effort gender: the driver's own attribute first, then name hints."""
    declared = getattr(voice, "gender", None)
    if declared:
        d = str(declared).strip().lower()
        if "female" in d or d == "f":
            return "female"
        if "male" in d or d == "m":
            return "male"
    if any(h in text for h in _FEMALE_NAME_HINTS):
        return "female"
    if any(h in text for h in _MALE_NAME_HINTS):
        return "male"
    return None


def score_voice(voice, prefer_lang: str = "en-gb", prefer_gender: str = "male") -> int:
    """Score an installed voice against a language/gender preference.

    Higher is better; a negative score means "not usable" (non-English).
    Scoring is additive so a non-English voice can never outrank an English
    one, and locale always outranks gender.
    """
    text = _voice_text(voice)

    is_gb = any(h in text for h in _GB_HINTS)
    is_us = any(h in text for h in _US_HINTS)
    # espeak ids are often bare ("english", "en"), so match those too.
    is_english = is_gb or is_us or "english" in text or "en" in text.split("-") or "/en" in text or text.strip() == "en"

    if not is_english:
        return -1

    score = 10  # baseline: usable English voice

    # Locale weight strictly exceeds the maximum gender swing (20 vs -5), so a
    # correct-locale voice of the "wrong" gender always beats a wrong-locale
    # voice of the right gender.
    want_gb = prefer_lang.lower().replace("_", "-") == "en-gb"
    if want_gb and is_gb:
        score += 60
    elif not want_gb and is_us:
        score += 60
    elif is_gb or is_us:
        score += 15  # right language, wrong locale — still far better than nothing

    gender = _voice_gender(voice, text)
    if gender == prefer_gender.lower():
        score += 20
    elif gender is not None:
        score -= 5  # known to be the other gender

    # espeak's "variant" voices (english+f3 etc.) are lower quality than base.
    if "+" in text:
        score -= 2

    return score


def select_voice(voices: list, prefer_lang: str = "en-gb", prefer_gender: str = "male"):
    """Pick the best installed voice, or None when nothing usable exists.

    Falls back to the first installed voice if none look English — better to
    speak with an unexpected accent than not at all.
    """
    if not voices:
        return None

    scored = [(score_voice(v, prefer_lang, prefer_gender), i, v) for i, v in enumerate(voices)]
    usable = [s for s in scored if s[0] >= 0]
    if not usable:
        logger.warning(
            "No English TTS voice found among %d installed voices; using the first available.",
            len(voices),
        )
        return voices[0]
    # index as tiebreaker keeps selection deterministic
    best = max(usable, key=lambda s: (s[0], -s[1]))
    return best[2]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class LocalTTS:
    """Singleton offline TTS engine (pyttsx3 / espeak-ng)."""

    _instance: Optional["LocalTTS"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._engine = None
        self._engine_lock = threading.Lock()
        self._init_attempted = False
        self._error: Optional[str] = None
        self._selected_voice_id: Optional[str] = None
        self._selected_voice_name: Optional[str] = None
        self._available_voice_count = 0

    @classmethod
    def get_instance(cls) -> "LocalTTS":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls):
        """Drop the singleton (used by tests)."""
        with cls._lock:
            cls._instance = None

    # -- status ------------------------------------------------------------

    def get_status(self) -> dict:
        """Inspectable engine state, surfaced to clients via the voice state
        machine so a missing espeak-ng shows up as a clear ERROR rather than
        silence."""
        self._ensure_engine()
        return {
            "available": self._engine is not None,
            "error": self._error,
            "voice_id": self._selected_voice_id,
            "voice_name": self._selected_voice_name,
            "voice_count": self._available_voice_count,
            "engine": "pyttsx3",
            "override_active": bool(TTS_VOICE_ID_OVERRIDE),
        }

    # -- init --------------------------------------------------------------

    def _ensure_engine(self):
        """Initialise the engine once. Never raises — failures are recorded in
        self._error so a broken audio stack cannot take the whole app down."""
        if self._engine is not None or self._init_attempted:
            return
        with self._engine_lock:
            if self._engine is not None or self._init_attempted:
                return
            self._init_attempted = True
            try:
                import pyttsx3
            except Exception as e:
                self._error = (
                    f"pyttsx3 is not installed ({e}). Install server/requirements.txt."
                )
                logger.error(self._error)
                return

            try:
                engine = pyttsx3.init()
            except Exception as e:
                self._error = (
                    f"Could not initialise a local speech engine ({e}). On Linux this "
                    f"usually means espeak-ng is missing — install it with "
                    f"`sudo apt install espeak-ng` (see README > Voice Setup)."
                )
                logger.error(self._error)
                return

            try:
                voices = list(engine.getProperty("voices") or [])
            except Exception as e:
                voices = []
                logger.warning("Could not enumerate TTS voices: %s", e)

            self._available_voice_count = len(voices)

            if not voices:
                self._error = (
                    "No TTS voices are installed on this host, so Nova cannot speak. "
                    "On Linux install espeak-ng (`sudo apt install espeak-ng`); on other "
                    "platforms install a system speech voice. See README > Voice Setup."
                )
                logger.error(self._error)
                try:
                    engine.stop()
                except Exception:
                    pass
                return

            chosen_id = None
            if TTS_VOICE_ID_OVERRIDE:
                chosen_id = TTS_VOICE_ID_OVERRIDE
                match = next((v for v in voices if str(getattr(v, "id", "")) == chosen_id), None)
                self._selected_voice_name = getattr(match, "name", None) if match else None
                if match is None:
                    logger.warning(
                        "TTS_VOICE_ID=%r is not among the %d installed voices; using it anyway "
                        "as the driver may still accept it.", chosen_id, len(voices),
                    )
            else:
                prefs = SUPPORTED_VOICES[DEFAULT_VOICE_KEY]
                chosen = select_voice(voices, prefs["lang"], prefs["gender"])
                if chosen is not None:
                    chosen_id = getattr(chosen, "id", None)
                    self._selected_voice_name = getattr(chosen, "name", None)

            try:
                engine.setProperty("rate", TTS_RATE)
                engine.setProperty("volume", TTS_VOLUME)
                if chosen_id:
                    engine.setProperty("voice", chosen_id)
            except Exception as e:
                logger.warning("Could not apply TTS voice properties: %s", e)

            self._selected_voice_id = chosen_id
            self._engine = engine
            self._error = None
            logger.info(
                "Local TTS ready (pyttsx3): voice=%s (%s) of %d installed",
                chosen_id, self._selected_voice_name, len(voices),
            )

    def _apply_requested_voice(self, voice: Optional[str]):
        """Resolve a requested voice (a SUPPORTED_VOICES key, or a raw platform
        voice id) against the installed voices and apply it."""
        if not voice or self._engine is None or TTS_VOICE_ID_OVERRIDE:
            return
        try:
            voices = list(self._engine.getProperty("voices") or [])
            if voice in SUPPORTED_VOICES:
                prefs = SUPPORTED_VOICES[voice]
                chosen = select_voice(voices, prefs["lang"], prefs["gender"])
                target = getattr(chosen, "id", None) if chosen else None
            else:
                # Raw platform voice id — only honour it if it truly exists.
                target = voice if any(str(getattr(v, "id", "")) == voice for v in voices) else None
            if target and target != self._selected_voice_id:
                self._engine.setProperty("voice", target)
                self._selected_voice_id = target
                self._selected_voice_name = next(
                    (getattr(v, "name", None) for v in voices if str(getattr(v, "id", "")) == target), None
                )
        except Exception as e:
            logger.warning("Could not switch TTS voice to %r: %s", voice, e)

    # -- synthesis ---------------------------------------------------------

    def _synthesize_blocking(self, text: str, voice: Optional[str] = None) -> bytes:
        self._ensure_engine()
        if self._engine is None:
            raise TTSUnavailableError(self._error or "Local TTS engine is unavailable.")

        with self._engine_lock:
            self._apply_requested_voice(voice)
            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name

                self._engine.save_to_file(text, tmp_path)
                self._engine.runAndWait()

                if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                    with open(tmp_path, "rb") as f:
                        return f.read()
                raise TTSUnavailableError(
                    "The local speech engine produced no audio. On Linux this usually means "
                    "espeak-ng is missing or misconfigured (see README > Voice Setup)."
                )
            except TTSUnavailableError:
                raise
            except Exception as e:
                raise TTSUnavailableError(f"Local TTS synthesis failed: {e}") from e
            finally:
                if tmp_path and os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

    async def synthesize_with_mime(self, text: str, voice: Optional[str] = None) -> Tuple[bytes, str]:
        """Synthesize to (audio_bytes, mime_type). Always WAV — pyttsx3's only
        output format. Raises TTSUnavailableError when no engine/voice exists so
        the caller can surface a real ERROR state."""
        if not text or not text.strip():
            return b"", "audio/wav"

        loop = asyncio.get_running_loop()
        wav_bytes = await loop.run_in_executor(None, self._synthesize_blocking, text, voice)
        return wav_bytes, "audio/wav"

    async def synthesize(self, text: str, voice: Optional[str] = None) -> bytes:
        audio, _ = await self.synthesize_with_mime(text, voice=voice)
        return audio

    def speak_blocking(self, text: str) -> None:
        """Speak directly through the default audio device (non-async contexts)."""
        self._ensure_engine()
        if self._engine is None:
            raise TTSUnavailableError(self._error or "Local TTS engine is unavailable.")
        with self._engine_lock:
            self._engine.say(text)
            self._engine.runAndWait()

    def stop(self) -> None:
        """Stop any in-progress speech immediately."""
        if self._engine is not None:
            try:
                self._engine.stop()
            except Exception:
                pass


def get_tts() -> LocalTTS:
    return LocalTTS.get_instance()
