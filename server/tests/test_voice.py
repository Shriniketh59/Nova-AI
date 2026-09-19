import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.voice_service import _clean_spoken_text, generate_voice_reply


def test_clean_spoken_text():
    raw = "Here is **bold** and *italic* text with `code` and # Header\n* Item 1\n* Item 2"
    cleaned = _clean_spoken_text(raw)
    assert "**" not in cleaned
    assert "*" not in cleaned
    assert "#" not in cleaned
    assert "`" not in cleaned
    assert "bold and italic text with and Header Item 1 Item 2" in cleaned


@pytest.mark.asyncio
async def test_voice_config_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.get("/api/voice/config")
        assert res.status_code == 200
        data = res.json()
        assert data["engine"] == "local"
        assert data["stt"] == "faster-whisper"
        assert data["geminiConfigured"] is False
        assert "wsEndpoint" in data


@pytest.mark.asyncio
async def test_voice_chat_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/voice/chat", json={"message": "hello Nova voice"})
        assert res.status_code == 200
        data = res.json()
        assert "reply" in data
        assert data["reply"] != ""
        assert data["success"] is True


@pytest.mark.asyncio
async def test_voice_retrieval_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://localhost:5001") as client:
        res = await client.post("/api/voice/retrieval", json={"query": "tallest player in NBA history"})
        assert res.status_code == 200
        data = res.json()
        assert "result" in data
        assert isinstance(data["result"], str)
        assert len(data["result"]) > 0
        assert "sources" in data


# ---------------------------------------------------------------------------
# Local TTS — voice selection logic.
#
# These run with no audio device and no espeak-ng: pyttsx3 is mocked, so only
# the selection/fallback logic is exercised. Actual audio output has to be
# verified on a host with espeak-ng installed.
# ---------------------------------------------------------------------------

class FakeVoice:
    """Mimics a pyttsx3 Voice. Drivers expose these attributes inconsistently,
    so every field is optional."""

    def __init__(self, id, name="", languages=None, gender=None):
        self.id = id
        self.name = name
        self.languages = languages if languages is not None else []
        self.gender = gender


def test_prefers_british_male_voice_when_available():
    from app.voice.local_tts import select_voice

    voices = [
        FakeVoice("us-female", "english-us", [b"\x05en-us"], "female"),
        FakeVoice("gb-female", "english-gb", [b"\x05en-gb"], "female"),
        FakeVoice("us-male", "english-us", [b"\x05en-us"], "male"),
        FakeVoice("gb-male", "english-gb", [b"\x05en-gb"], "male"),
    ]
    assert select_voice(voices, "en-gb", "male").id == "gb-male"


def test_locale_outranks_gender():
    """An en-GB female beats an en-US male when en-GB is preferred."""
    from app.voice.local_tts import select_voice

    voices = [
        FakeVoice("us-male", "english-us", [b"\x05en-us"], "male"),
        FakeVoice("gb-female", "english-gb", [b"\x05en-gb"], "female"),
    ]
    assert select_voice(voices, "en-gb", "male").id == "gb-female"


def test_falls_back_to_other_english_locale_when_no_en_gb_installed():
    from app.voice.local_tts import select_voice

    voices = [
        FakeVoice("us-female", "english-us", [b"\x05en-us"], "female"),
        FakeVoice("us-male", "english-us", [b"\x05en-us"], "male"),
    ]
    assert select_voice(voices, "en-gb", "male").id == "us-male"


def test_detects_locale_and_gender_from_espeak_style_ids_without_metadata():
    """espeak often reports no gender and a bare id like 'english+m3'."""
    from app.voice.local_tts import select_voice

    voices = [
        FakeVoice("english+f3", "english+f3"),
        FakeVoice("en-gb+m2", "en-gb+m2"),
        FakeVoice("en-us+m1", "en-us+m1"),
    ]
    assert select_voice(voices, "en-gb", "male").id == "en-gb+m2"


def test_falls_back_to_first_voice_when_none_are_english():
    from app.voice.local_tts import select_voice

    voices = [FakeVoice("de", "deutsch", [b"\x02de"]), FakeVoice("fr", "francais", [b"\x02fr"])]
    assert select_voice(voices, "en-gb", "male").id == "de"


def test_select_voice_returns_none_when_no_voices_installed():
    from app.voice.local_tts import select_voice

    assert select_voice([]) is None


def test_selection_is_deterministic_for_equally_scored_voices():
    from app.voice.local_tts import select_voice

    voices = [FakeVoice("gb-male-a", "english-gb", [b"\x05en-gb"], "male"),
              FakeVoice("gb-male-b", "english-gb", [b"\x05en-gb"], "male")]
    assert select_voice(voices, "en-gb", "male").id == "gb-male-a"
    assert select_voice(list(voices), "en-gb", "male").id == "gb-male-a"


# -- missing-voice / missing-engine error handling --------------------------

def _install_fake_pyttsx3(monkeypatch, voices, init_error=None):
    """Install a fake pyttsx3 module and reset the TTS singleton."""
    import sys
    import types

    from app.voice.local_tts import LocalTTS

    class FakeEngine:
        def __init__(self):
            self.properties = {}

        def getProperty(self, key):
            return voices if key == "voices" else self.properties.get(key)

        def setProperty(self, key, value):
            self.properties[key] = value

        def save_to_file(self, text, path):
            pass

        def runAndWait(self):
            pass

        def stop(self):
            pass

    engine = FakeEngine()

    def init(*args, **kwargs):
        if init_error:
            raise init_error
        return engine

    module = types.ModuleType("pyttsx3")
    module.init = init
    monkeypatch.setitem(sys.modules, "pyttsx3", module)
    LocalTTS.reset_instance()
    return engine


def test_no_voices_installed_reports_a_clear_error_and_does_not_crash(monkeypatch):
    from app.voice.local_tts import get_tts

    _install_fake_pyttsx3(monkeypatch, voices=[])
    status = get_tts().get_status()

    assert status["available"] is False
    assert status["voice_count"] == 0
    # Error must be explicit and actionable, not silent.
    assert status["error"]
    assert "espeak-ng" in status["error"]
    from app.voice.local_tts import LocalTTS
    LocalTTS.reset_instance()


@pytest.mark.asyncio
async def test_synthesis_raises_a_typed_error_when_no_voices_exist(monkeypatch):
    from app.voice.local_tts import LocalTTS, TTSUnavailableError, get_tts

    _install_fake_pyttsx3(monkeypatch, voices=[])
    with pytest.raises(TTSUnavailableError):
        await get_tts().synthesize("hello")
    LocalTTS.reset_instance()


def test_engine_init_failure_is_captured_not_raised(monkeypatch):
    from app.voice.local_tts import LocalTTS, get_tts

    _install_fake_pyttsx3(monkeypatch, voices=[], init_error=OSError("no audio backend"))
    status = get_tts().get_status()
    assert status["available"] is False
    assert "espeak-ng" in status["error"]
    LocalTTS.reset_instance()


def test_auto_selects_en_gb_male_on_init(monkeypatch):
    from app.voice.local_tts import LocalTTS, get_tts

    voices = [
        FakeVoice("english-us", "english-us", [b"\x05en-us"], "female"),
        FakeVoice("english-gb", "english-gb", [b"\x05en-gb"], "male"),
    ]
    _install_fake_pyttsx3(monkeypatch, voices=voices)
    status = get_tts().get_status()
    assert status["available"] is True
    assert status["voice_id"] == "english-gb"
    LocalTTS.reset_instance()


def test_tts_voice_id_env_var_overrides_auto_detection(monkeypatch):
    import app.voice.local_tts as tts_module
    from app.voice.local_tts import LocalTTS

    voices = [FakeVoice("english-gb", "english-gb", [b"\x05en-gb"], "male")]
    _install_fake_pyttsx3(monkeypatch, voices=voices)
    monkeypatch.setattr(tts_module, "TTS_VOICE_ID_OVERRIDE", "my-custom-voice")
    LocalTTS.reset_instance()

    status = tts_module.get_tts().get_status()
    assert status["voice_id"] == "my-custom-voice", "explicit override must win over auto-detection"
    assert status["override_active"] is True
    LocalTTS.reset_instance()


def test_no_cloud_tts_dependency_is_referenced():
    """Guard against edge-tts (a Microsoft cloud API) creeping back in."""
    import pathlib

    source = pathlib.Path(__file__).parent.parent / "app" / "voice" / "local_tts.py"
    text = source.read_text().lower()
    assert "edge_tts" not in text and "edge-tts" not in text
    assert "siri" not in text.replace("no siri-branded", "")


def test_supported_voices_carry_no_siri_or_cloud_branding():
    from app.voice.local_tts import SUPPORTED_VOICES

    for key, meta in SUPPORTED_VOICES.items():
        assert "siri" not in key.lower()
        assert "siri" not in meta["label"].lower()
        assert "neural" not in meta["label"].lower()
