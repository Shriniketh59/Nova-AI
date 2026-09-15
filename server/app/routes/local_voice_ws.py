"""
Local Voice WebSocket route.

WS /ws/voice/local

Full local voice pipeline:
  Browser sends PCM audio chunks →
  faster-whisper STT (local) →
  Local Orchestrator (Llama 3.2 via Ollama) →
  pyttsx3 + espeak-ng TTS (local) →
  WAV audio bytes → Browser plays audio

Protocol (client → server):
  {"type": "audio_chunk", "data": "<base64 16kHz 16-bit PCM>"}  — mic chunk
  {"type": "audio_end"}                                          — end of utterance
  {"type": "stop"}                                               — stop TTS + reset
  {"type": "text", "text": "..."}                               — text input (no STT)

Protocol (server → client):
  {"type": "ready"}                                — connected
  {"type": "listening"}                            — ready for mic input
  {"type": "transcript", "text": "..."}           — STT result
  {"type": "thinking"}                             — orchestrator running
  {"type": "token", "text": "..."}                — streaming Llama token
  {"type": "tts_audio", "data": "<base64 WAV>"}   — synthesized audio
  {"type": "speaking"}                             — TTS started
  {"type": "done"}                                 — turn complete
  {"type": "error", "message": "..."}             — error
  {"type": "interrupted"}                          — playback stopped by barge-in
"""
import asyncio
import base64
import io
import logging
import wave
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from ..core.logger import logger

router = APIRouter()
_log = logging.getLogger("nova.voice_ws")

# Buffer 0.5s of silence before ending an utterance (at 16kHz, 16-bit = 16000 bytes/s)
MIN_AUDIO_BYTES_FOR_TRANSCRIPTION = 8000  # ~0.25s of audio


@router.websocket("/ws/voice/local")
async def local_voice_ws(websocket: WebSocket):
    """
    Full local voice session over WebSocket.
    - STT: faster-whisper (local)
    - LLM: llama3.2:3b via Ollama (local)
    - TTS: pyttsx3 + espeak-ng (local)
    No external APIs used.
    """
    await websocket.accept()
    chat_id = websocket.query_params.get("chatId", "")

    conversation_history: list[dict] = []
    audio_buffer = bytearray()
    tts_stop_event = asyncio.Event()
    is_speaking = False

    async def safe_send(data: dict):
        try:
            await websocket.send_json(data)
        except Exception:
            pass

    await safe_send({"type": "ready"})
    await safe_send({"type": "listening"})

    async def handle_turn(transcript: str):
        nonlocal is_speaking

        if not transcript.strip():
            await safe_send({"type": "listening"})
            return

        await safe_send({"type": "transcript", "text": transcript})
        await safe_send({"type": "thinking"})

        # Add user turn to history
        conversation_history.append({"role": "user", "content": transcript})

        # Stream orchestrator response
        from ..orchestrator.local_orchestrator import orchestrate_stream
        full_text = ""
        sources = []

        try:
            async for event in orchestrate_stream(
                query=transcript,
                chat_id=chat_id,
                conversation_history=conversation_history[:-1],  # exclude current turn
                is_voice=True,
            ):
                if tts_stop_event.is_set():
                    break
                if "sources" in event:
                    sources = event["sources"]
                elif "token" in event:
                    full_text += event["token"]
                    await safe_send({"type": "token", "text": event["token"]})
                elif "replace" in event:
                    full_text = event["replace"]
                elif "error" in event:
                    await safe_send({"type": "error", "message": event["error"]})
                    return
        except Exception as e:
            logger.error("voice_ws.orchestrate_failed", {"error": str(e)})
            await safe_send({"type": "error", "message": str(e)})
            return

        if not full_text.strip():
            await safe_send({"type": "done"})
            await safe_send({"type": "listening"})
            return

        # Add assistant turn to history
        conversation_history.append({"role": "assistant", "content": full_text})
        # Keep history bounded
        if len(conversation_history) > 12:
            conversation_history[:] = conversation_history[-12:]

        # TTS synthesis
        tts_stop_event.clear()
        is_speaking = True
        await safe_send({"type": "speaking"})

        from ..voice.local_voice_service import synthesize_speech
        wav_bytes = await synthesize_speech(full_text)

        if tts_stop_event.is_set():
            await safe_send({"type": "interrupted"})
            is_speaking = False
            await safe_send({"type": "listening"})
            return

        if wav_bytes:
            audio_b64 = base64.b64encode(wav_bytes).decode("utf-8")
            await safe_send({
                "type": "tts_audio",
                "data": audio_b64,
                "mimeType": "audio/wav",
            })

        is_speaking = False
        await safe_send({"type": "done"})
        await safe_send({"type": "listening"})

    try:
        while True:
            try:
                msg_text = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            except Exception:
                break

            try:
                import json
                msg = json.loads(msg_text)
            except Exception:
                continue

            msg_type = msg.get("type", "")

            if msg_type == "audio_chunk":
                # Accumulate raw PCM bytes
                b64_data = msg.get("data", "")
                if b64_data:
                    try:
                        pcm_bytes = base64.b64decode(b64_data)
                        audio_buffer.extend(pcm_bytes)
                    except Exception as e:
                        _log.warning(f"Bad audio chunk: {e}")

            elif msg_type == "audio_end":
                # End of utterance — transcribe accumulated buffer
                if len(audio_buffer) >= MIN_AUDIO_BYTES_FOR_TRANSCRIPTION:
                    raw_pcm = bytes(audio_buffer)
                    audio_buffer.clear()

                    # Wrap in WAV for faster-whisper
                    wav_buf = io.BytesIO()
                    with wave.open(wav_buf, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)       # 16-bit
                        wf.setframerate(16000)   # 16kHz
                        wf.writeframes(raw_pcm)
                    wav_bytes_in = wav_buf.getvalue()

                    # STT
                    from ..voice.local_stt import get_stt
                    stt = get_stt()
                    loop = asyncio.get_running_loop()
                    transcript = await loop.run_in_executor(
                        None, stt.transcribe_bytes, wav_bytes_in
                    )

                    if transcript:
                        await handle_turn(transcript)
                    else:
                        # No speech detected
                        await safe_send({"type": "listening"})
                else:
                    audio_buffer.clear()
                    await safe_send({"type": "listening"})

            elif msg_type == "text":
                # Direct text input (no STT needed)
                text_input = msg.get("text", "").strip()
                if text_input:
                    await handle_turn(text_input)

            elif msg_type == "stop":
                # Barge-in / stop playback
                tts_stop_event.set()
                audio_buffer.clear()
                await safe_send({"type": "interrupted"})
                await safe_send({"type": "listening"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("voice_ws.session_failed", {"error": str(e)})
        try:
            await safe_send({"type": "error", "message": str(e)})
        except Exception:
            pass
