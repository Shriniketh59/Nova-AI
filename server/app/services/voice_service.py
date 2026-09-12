import asyncio
import os
import re
from datetime import datetime
import requests

from ..core.config import OLLAMA_URL, OLLAMA_MODEL, GEMINI_API_KEY
from ..core.logger import logger


LANG_MAP = {
    "auto": ("Auto", "auto"),
    "ta-in": ("Tamil", "ta-IN"),
    "tamil": ("Tamil", "ta-IN"),
    "hi-in": ("Hindi", "hi-IN"),
    "hindi": ("Hindi", "hi-IN"),
    "te-in": ("Telugu", "te-IN"),
    "telugu": ("Telugu", "te-IN"),
    "ml-in": ("Malayalam", "ml-IN"),
    "malayalam": ("Malayalam", "ml-IN"),
    "kn-in": ("Kannada", "kn-IN"),
    "kannada": ("Kannada", "kn-IN"),
    "en-in": ("English", "en-IN"),
    "en-us": ("English", "en-US"),
    "english": ("English", "en-IN"),
}


def detect_script_language(text: str) -> tuple[str, str]:
    """Detect language and BCP-47 tag based on Unicode script characters."""
    if not text:
        return ("English", "en-IN")
    if re.search(r"[\u0B80-\u0BFF]", text):
        return ("Tamil", "ta-IN")
    if re.search(r"[\u0900-\u097F]", text):
        return ("Hindi", "hi-IN")
    if re.search(r"[\u0C00-\u0C7F]", text):
        return ("Telugu", "te-IN")
    if re.search(r"[\u0D00-\u0D7F]", text):
        return ("Malayalam", "ml-IN")
    if re.search(r"[\u0C80-\u0CFF]", text):
        return ("Kannada", "kn-IN")
    return ("English", "en-IN")


def resolve_language(lang_param: str | None, text: str) -> tuple[str, str]:
    """Resolve target language name and BCP-47 code from explicit preference or script detection."""
    if lang_param:
        norm = lang_param.strip().lower()
        if norm in LANG_MAP:
            return LANG_MAP[norm]
        for k, v in LANG_MAP.items():
            if k in norm:
                return v

    return detect_script_language(text)


def _clean_spoken_text(text: str) -> str:
    """Strip markdown formatting and awkward parenthetical transliterations so TTS sounds crystal clear."""
    if not text:
        return ""
    cleaned = re.sub(r"\*\*?(.*?)\*\*?", r"\1", text)
    cleaned = re.sub(r"#+\s*", "", cleaned)
    cleaned = re.sub(r"`{1,3}[^`]*`{1,3}", "", cleaned)
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"^[\*\-\+]\s+", "", cleaned, flags=re.MULTILINE)

    # If text contains Indic script (Tamil, Hindi, Telugu, Malayalam, Kannada),
    # strip redundant English parentheticals like "(Vanakkam)" or "(Namaste)" which confuse Indic TTS
    if re.search(r"[\u0900-\u0D7F]", cleaned):
        cleaned = re.sub(r"\([A-Za-z0-9\s,\.!?-]+\)", "", cleaned)

    # Replace symbols with clear pronounceable words
    cleaned = cleaned.replace("&", " and ").replace("%", " percent ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _needs_fresh_search(msg: str) -> bool:
    """Only query live web search if user explicitly asks for breaking external news or live updates.

    Conversational queries, general knowledge, greetings, and date checks do not need external search.
    """
    lower = msg.lower()
    explicit_search_triggers = [
        "latest news", "breaking news", "today's headlines", "weather forecast",
        "current weather", "live score", "cricket score", "stock price",
        "gold rate", "election results", "live match",
        "இன்றைய செய்திகள்", "நேரலை", "வானிலை",   # Tamil live triggers
        "ताज़ा खबर", "आज के समाचार", "मौसम",      # Hindi live triggers
        "తాజా వార్తలు", "వాతావరణం",               # Telugu live triggers
        "ഇന്നത്തെ വാർത്തകൾ",                     # Malayalam live triggers
        "ಇಂದಿನ ಮುಖ್ಯಾಂಶಗಳು",                       # Kannada live triggers
    ]
    return any(t in lower or t in msg for t in explicit_search_triggers)


async def _fetch_live_web_context(query: str, current_date_str: str) -> str:
    """Retrieve fast live search snippets with strict 1.5s timeout so voice latency stays ultra-fast."""
    try:
        from ..retrieval.web_retriever import get_web_retriever
        retriever = get_web_retriever()
        results = await asyncio.wait_for(retriever.search(query, max_results=2), timeout=1.8)
        if results:
            snippets = []
            for r in results:
                title = r.title.strip()
                content = r.content[:200].strip() if r.content else ""
                if content:
                    snippets.append(f"- {title}: {content}")
            if snippets:
                return f"\n[CURRENT LIVE WEB CONTEXT as of {current_date_str}]:\n" + "\n".join(snippets) + "\n"
    except Exception as err:
        logger.warn(f"Live web search grounding skipped: {err}")
    return ""


async def generate_voice_reply(
    message: str,
    api_key: str | None = None,
    model_name: str | None = None,
    language: str | None = None,
    lang_code: str | None = None,
    conversation_history: list[dict] | None = None,
) -> dict:
    """Generate an ultra-fast, natural conversational response in Tamil, English, Telugu, Malayalam,

    Kannada, or Hindi using Google Gemini with dynamic auto-detection and accurate translation.
    """
    active_key = api_key or os.environ.get("GEMINI_API_KEY") or GEMINI_API_KEY
    if not active_key:
        from dotenv import find_dotenv, load_dotenv
        load_dotenv(find_dotenv(), override=True)
        active_key = os.environ.get("GEMINI_API_KEY")

    # Resolve target language and BCP-47 tag
    lang_param = language or lang_code
    lang_name, target_lang_tag = resolve_language(lang_param, message)

    # Real-time temporal anchor
    now = datetime.now()
    current_date_str = now.strftime("%A, %B %d, %Y")

    # Only fetch external web search if explicitly requested
    live_web_context = ""
    if _needs_fresh_search(message):
        live_web_context = await _fetch_live_web_context(message, current_date_str)

    if lang_name == "Auto":
        lang_rule = """- LANGUAGE & AUTO-DETECTION:
Detect the language of the user query (Tamil, English, Hindi, Telugu, Malayalam, or Kannada) and reply fluently in that exact same language.
If the user asks to translate a sentence or phrase between languages (e.g., "translate to Tamil" or "say this in English"), provide the exact, accurate translation directly and clearly."""
    else:
        lang_rule = f"""- LANGUAGE & TRANSLATION:
Converse naturally and fluently in {lang_name} ({target_lang_tag}).
If the user asks to translate a sentence or phrase into a specific language, ALWAYS provide the exact, accurate translation into that requested language."""

    system_instruction = f"""You are Nova Voice, a fast, intelligent, warm, and natural conversational voice assistant.
REAL-TIME TEMPORAL ANCHOR:
Today's real-world date is: {current_date_str}.
Always anchor your answers to this date and use the current real-world knowledge provided.

MANDATORY RULES FOR SPOKEN AUDIO INTERACTION:
1. Speak naturally, concisely, and conversationally in 1-2 spoken sentences. Deliver direct, accurate, engaging answers with zero filler.
2. {lang_rule}
3. Do NOT use markdown symbols like asterisks (*, **), bullet points, headers (#), URLs, or code fences, because this will be spoken aloud by a voice synthesizer.
4. Pronounce acronyms, numbers, and dates naturally for spoken listening.
{live_web_context}
"""

    # Map deprecated model names to current flash models
    if not model_name or model_name in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.5-flash"]:
        chosen_model = os.environ.get("GEMINI_VOICE_MODEL", "gemini-flash-lite-latest")
    else:
        chosen_model = model_name

    if active_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=active_key)

            gen_config = genai.GenerationConfig(
                max_output_tokens=300,
                temperature=0.6,
            )

            # Format history if available
            contents = []
            if conversation_history:
                for msg in conversation_history[-6:]:
                    role = "user" if msg.get("role") == "user" else "model"
                    contents.append({"role": role, "parts": [msg.get("content", "")]})

            # Combine system instruction and query in the prompt turn to ensure full complete sentence generation
            user_turn = f"{system_instruction}\n\nUser Question: {message}"
            contents.append({"role": "user", "parts": [user_turn]})

            # Cascade across fastest flash models to bypass single-model quota limits
            candidates = [chosen_model]
            for fallback_m in ["gemini-flash-lite-latest", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-flash-latest", "gemini-3.8-flash"]:
                if fallback_m not in candidates:
                    candidates.append(fallback_m)

            for cm in candidates:
                try:
                    model = genai.GenerativeModel(
                        model_name=cm,
                        generation_config=gen_config,
                    )
                    response = model.generate_content(contents)
                    raw_text = response.text if response and hasattr(response, "text") else ""
                    if raw_text:
                        cleaned = _clean_spoken_text(raw_text)
                        # Re-verify language of response for TTS voice routing
                        resp_lang, resp_tag = detect_script_language(cleaned)
                        final_tag = resp_tag if target_lang_tag in ["auto", "en-IN"] else target_lang_tag
                        final_lang = resp_lang if lang_name in ["Auto", "English"] else lang_name

                        return {
                            "reply": cleaned,
                            "engine": "gemini",
                            "model": cm,
                            "language": final_lang,
                            "langCode": final_tag,
                            "success": True,
                        }
                except Exception as m_err:
                    logger.warn(f"Model {cm} voice attempt failed: {m_err}")
                    continue
        except Exception as err:
            logger.error(f"Gemini voice call failed, falling back to local model: {err}")

    # Fallback to local Ollama
    try:
        messages = [{"role": "system", "content": system_instruction}]
        if conversation_history:
            for msg in conversation_history[-6:]:
                role = "user" if msg.get("role") == "user" else "assistant"
                messages.append({"role": role, "content": msg.get("content", "")})
        messages.append({"role": "user", "content": message})

        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 100},
            },
            timeout=20,
        )
        if resp.status_code == 200:
            data = resp.json()
            raw_reply = data.get("message", {}).get("content", "")
            cleaned = _clean_spoken_text(raw_reply)
            resp_lang, resp_tag = detect_script_language(cleaned)
            return {
                "reply": cleaned,
                "engine": "ollama",
                "model": OLLAMA_MODEL,
                "language": resp_lang or lang_name,
                "langCode": resp_tag or target_lang_tag,
                "success": True,
            }
    except Exception as err:
        logger.error(f"Local voice fallback failed: {err}")

    return {
        "reply": "I am having trouble connecting to the voice service right now. Please check your network or settings.",
        "engine": "none",
        "model": "none",
        "language": lang_name,
        "langCode": target_lang_tag,
        "success": False,
    }
