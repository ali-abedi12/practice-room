"""
The model-access layer: every AI call in the app goes through ask_model().

Why one place?
- Swapping provider or model means changing this file (and config.py) only.
- Cost, token and timing logging happens automatically for every call.
- Retries and friendly failures are handled once, not in every screen.

Privacy choice: we log numbers (tokens, cost, time), never what the student typed.
"""

import csv
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from dotenv import load_dotenv

import config

load_dotenv()  # reads GEMINI_API_KEY from a local .env file, if there is one


@dataclass
class ModelReply:
    text: str
    ok: bool                  # False means the call failed and text is empty
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0


class ModelUnavailable(Exception):
    """Raised when the model can't be reached after retries."""


# ---------------------------------------------------------------------------
# API key: never in the code. Locally it comes from .env, on Streamlit Cloud
# from the app's Secrets settings.
# ---------------------------------------------------------------------------
def _get_api_key():
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    try:
        import streamlit as st
        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        return None


_client = None


def _gemini_client():
    # Created once and reused, instead of a new connection per message.
    global _client
    if _client is None:
        from google import genai
        from google.genai import types

        key = _get_api_key()
        if not key:
            raise ModelUnavailable("No GEMINI_API_KEY set. See README.")
        _client = genai.Client(
            api_key=key,
            http_options=types.HttpOptions(timeout=config.REQUEST_TIMEOUT_SECONDS * 1000),
        )
    return _client


def estimate_cost(model, input_tokens, output_tokens):
    price = config.PRICES.get(model)
    if not price:
        return 0.0
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000


# ---------------------------------------------------------------------------
# The one public function
# ---------------------------------------------------------------------------
def ask_model(task, system, messages, session_id, json_output=False, temperature=0.8):
    """
    task:       "chat" or "grade" - picks the model from config.MODELS
    system:     the hidden instructions (persona, rules)
    messages:   list of {"role": "user" | "assistant", "content": "..."}
    session_id: links this call to one student session in the logs
    """
    model = config.MODELS[task]
    provider = os.getenv("LLM_PROVIDER", "gemini")

    last_error = None
    for attempt in range(config.RETRIES + 1):
        start = time.time()
        try:
            if provider == "fake":
                text, tin, tout = _call_fake(task, messages)
            else:
                text, tin, tout = _call_gemini(model, system, messages, json_output, temperature)

            reply = ModelReply(
                text=text,
                ok=True,
                input_tokens=tin,
                output_tokens=tout,
                cost_usd=estimate_cost(model, tin, tout),
                seconds=round(time.time() - start, 2),
            )
            _log_call(session_id, task, model, reply, status="ok")
            return reply

        except ModelUnavailable:
            raise
        except Exception as e:  # rate limits, timeouts, server errors
            last_error = e
            _log_call(session_id, task, model, ModelReply("", False, seconds=round(time.time() - start, 2)),
                      status=f"error:{type(e).__name__}")
            if attempt < config.RETRIES:
                time.sleep(2 ** attempt)  # wait 1s, then 2s: "exponential backoff"

    raise ModelUnavailable(str(last_error))


def _call_gemini(model, system, messages, json_output, temperature):
    from google.genai import types

    # Gemini calls the AI's turns "model" rather than "assistant".
    contents = [
        types.Content(
            role="model" if m["role"] == "assistant" else "user",
            parts=[types.Part(text=m["content"])],
        )
        for m in messages
    ]
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if json_output else None,
    )
    resp = _gemini_client().models.generate_content(model=model, contents=contents, config=cfg)

    usage = resp.usage_metadata
    tin = usage.prompt_token_count or 0
    # "Thinking" tokens are billed as output, so count them too.
    tout = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
    return (resp.text or "").strip(), tin, tout


def _call_fake(task, messages):
    """Offline stand-in used only for testing the app without an API key."""
    if task == "grade":
        return ('{"deal_reached": true, "price_per_kg": 41, "monthly_kg": 200, "months": 6, '
                '"payment_terms": "30 days", "score": 6, "summary": "Test feedback.", '
                '"strengths": ["Opened with a clear number"], '
                '"improvements": ["Ask what the supplier needs before conceding"], '
                '"missed_opportunity": "Faster payment could have lowered the price."}'), 900, 150
    moods = ["neutral", "thinking", "pleased", "firm"]
    mood = moods[len(messages) // 2 % 4]
    return (f"(test reply {len(messages)}) Our standard price is QAR 52 per kg, "
            f"but I'm listening.\n[mood: {mood}]"), 400, 30


# ---------------------------------------------------------------------------
# Voice: speech-to-text and text-to-speech
# ---------------------------------------------------------------------------
TRANSCRIBE_PROMPT = (
    "Transcribe this recording exactly as spoken. It is a business negotiation "
    "and may be in English or Arabic. Return only the transcript, with no notes. "
    "If nothing intelligible is said, return an empty string."
)


def transcribe(audio_bytes, mime_type, session_id):
    """Student's voice -> text. Uses the same chat model, so it is cheap and logged."""
    model = config.MODELS[config.TRANSCRIBE_TASK]
    start = time.time()
    try:
        if os.getenv("LLM_PROVIDER") == "fake":
            text, tin, tout = "I can offer 40 riyals per kilo if we sign for six months.", 300, 20
        else:
            from google.genai import types
            resp = _gemini_client().models.generate_content(
                model=model,
                contents=[types.Content(role="user", parts=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                    types.Part(text=TRANSCRIBE_PROMPT),
                ])],
                config=types.GenerateContentConfig(temperature=0),
            )
            usage = resp.usage_metadata
            tin = usage.prompt_token_count or 0
            tout = (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0)
            text = (resp.text or "").strip().strip('"')
    except ModelUnavailable:
        raise
    except Exception as e:
        _log_call(session_id, "transcribe", model,
                  ModelReply("", False, seconds=round(time.time() - start, 2)),
                  status=f"error:{type(e).__name__}")
        raise ModelUnavailable(str(e))

    reply = ModelReply(text, True, tin, tout, estimate_cost(model, tin, tout),
                       round(time.time() - start, 2))
    _log_call(session_id, "transcribe", model, reply, status="ok")
    return reply


@dataclass
class Speech:
    audio: bytes
    mime_type: str
    provider: str
    cost_usd: float = 0.0


def speak(text, lang, mood, session_id):
    """
    Text -> audio. Tries each provider in config.TTS_PROVIDERS in order.
    Returns None if they all fail: the caller then simply shows text.
    """
    if os.getenv("LLM_PROVIDER") == "fake":
        return Speech(_fake_speech(text), "audio/wav", "fake")

    for provider in config.TTS_PROVIDERS:
        start = time.time()
        model = config.GEMINI_TTS_MODEL if provider == "gemini" else "edge-tts"
        try:
            if provider == "gemini":
                audio, mime = _tts_gemini(text, mood)
            elif provider == "edge":
                audio, mime = _tts_edge(text, lang)
            else:
                continue

            # TTS doesn't report tokens the way chat does, so we estimate:
            # ~4 characters per input token, ~25 audio tokens per second of speech.
            seconds_of_speech = len(text) / 14
            tin, tout = len(text) // 4, int(seconds_of_speech * 25)
            cost = estimate_cost(model, tin, tout)
            _log_call(session_id, "speak", model,
                      ModelReply("", True, tin, tout, cost, round(time.time() - start, 2)),
                      status="ok")
            return Speech(audio, mime, provider, cost)
        except Exception as e:
            _log_call(session_id, "speak", model,
                      ModelReply("", False, seconds=round(time.time() - start, 2)),
                      status=f"error:{type(e).__name__}")
    return None


def _tts_gemini(text, mood):
    import base64
    style = config.VOICE_STYLES.get(mood, config.VOICE_STYLES["neutral"])
    result = _gemini_client().interactions.create(
        model=config.GEMINI_TTS_MODEL,
        input=[{
            "type": "user_input",
            "content": [{
                "type": "text",
                "text": text,
                "annotations": [{"type": "speech_metadata", "style": style}],
            }],
        }],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": config.GEMINI_VOICE}]},
    )
    data = result.output_audio.data
    audio = base64.b64decode(data) if isinstance(data, str) else data
    if not audio:
        raise RuntimeError("empty audio")
    return audio, "audio/wav"   # 24 kHz mono WAV, per Google's docs


def _tts_edge(text, lang):
    import asyncio
    import edge_tts

    async def run():
        chunks = []
        comm = edge_tts.Communicate(text, config.EDGE_VOICES.get(lang, config.EDGE_VOICES["en"]))
        async for part in comm.stream():
            if part["type"] == "audio":
                chunks.append(part["data"])
        return b"".join(chunks)

    audio = asyncio.run(asyncio.wait_for(run(), timeout=config.REQUEST_TIMEOUT_SECONDS))
    if not audio:
        raise RuntimeError("empty audio")
    return audio, "audio/mpeg"


def _fake_speech(text):
    """A humming WAV with syllable-like pulses, so the avatar's mouth can be tested offline."""
    import io
    import math
    import struct
    import wave

    rate = 16000
    seconds = min(6.0, max(1.5, len(text) / 14))
    frames = bytearray()
    for i in range(int(rate * seconds)):
        t_ = i / rate
        envelope = max(0.0, math.sin(2 * math.pi * 3.5 * t_)) ** 2   # ~3.5 "syllables" a second
        sample = 0.4 * envelope * math.sin(2 * math.pi * 160 * t_)
        frames += struct.pack("<h", int(sample * 32767))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Logging: one CSV row per call
# ---------------------------------------------------------------------------
CALLS_LOG = os.path.join(config.LOG_DIR, "model_calls.csv")
CALLS_FIELDS = ["timestamp", "session_id", "task", "model", "status",
                "input_tokens", "output_tokens", "cost_usd", "seconds"]


def _log_call(session_id, task, model, reply, status):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(CALLS_LOG)
    with open(CALLS_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CALLS_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            "task": task,
            "model": model,
            "status": status,
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "cost_usd": f"{reply.cost_usd:.6f}",
            "seconds": reply.seconds,
        })
