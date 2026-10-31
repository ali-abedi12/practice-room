"""
The model-access layer: every AI call in the app goes through this file.

- chat_stream():  the character's reply, streamed word by word (optionally hearing audio)
- complete_json(): one-shot JSON answers (grading, drafting scenarios)
- transcribe():   speech -> text, used only as a fallback
- speak():        text -> speech, trying each voice provider in order

Every call is logged with tokens, estimated cost and time. What students say is never logged.
Set LLM_PROVIDER=fake to run everything offline with canned replies (for testing).
"""

import asyncio
import base64
import csv
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from dotenv import load_dotenv

import config

load_dotenv()


class ModelUnavailable(Exception):
    """The model couldn't be reached after retries."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)


def fake_mode():
    return os.getenv("LLM_PROVIDER", "gemini") == "fake"


def estimate_cost(model, tin, tout):
    p = config.PRICES.get(model)
    return (tin * p["input"] + tout * p["output"]) / 1_000_000 if p else 0.0


_client = None


def _gemini():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise ModelUnavailable("No GEMINI_API_KEY set. See README.")
        _client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=config.REQUEST_TIMEOUT_SECONDS * 1000))
    return _client


def _contents(history, audio=None):
    """Our message list -> Gemini's format. Gemini calls the AI's turns 'model'."""
    from google.genai import types
    out = [types.Content(role="model" if m["role"] == "assistant" else "user",
                         parts=[types.Part(text=m["content"])]) for m in history]
    if audio:
        data, mime = audio
        out.append(types.Content(role="user", parts=[
            types.Part.from_bytes(data=data, mime_type=mime),
            types.Part(text="(This recording is the student's latest turn.)"),
        ]))
    return out


def _config(task, system=None, json_output=False, temperature=0.7):
    from google.genai import types
    return types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        response_mime_type="application/json" if json_output else None,
        thinking_config=types.ThinkingConfig(thinking_level=config.THINKING[task]),
    )


def _usage_from(meta):
    if not meta:
        return 0, 0
    tin = meta.prompt_token_count or 0
    tout = (meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0)  # thinking is billed
    return tin, tout


# ---------------------------------------------------------------------------
# Streaming chat
# ---------------------------------------------------------------------------
async def chat_stream(system, history, session_id, audio=None, usage=None, temperature=0.7):
    """
    Async generator of text chunks. Pass a Usage object to have it filled in at the end.
    audio: optional (bytes, mime) - the model hears it directly, saving a separate
    transcription call (the system prompt asks it to write down what it heard first).
    """
    model = config.MODELS["chat"]
    usage = usage if usage is not None else Usage()
    start = time.time()
    if fake_mode():
        async for chunk in _fake_chat(history, audio):
            yield chunk
        usage.input_tokens, usage.output_tokens = 500, 40
    else:
        last_err = None
        for attempt in range(config.RETRIES + 1):
            try:
                sent_any = False
                meta = None
                stream = await _gemini().aio.models.generate_content_stream(
                    model=model, contents=_contents(history, audio),
                    config=_config("chat", system, temperature=temperature))
                async for chunk in stream:
                    if chunk.usage_metadata:
                        meta = chunk.usage_metadata
                    if chunk.text:
                        sent_any = True
                        yield chunk.text
                usage.input_tokens, usage.output_tokens = _usage_from(meta)
                last_err = None
                break
            except ModelUnavailable:
                raise
            except Exception as e:
                last_err = e
                _log(session_id, "chat", model, Usage(seconds=round(time.time() - start, 2)),
                     f"error:{type(e).__name__}")
                if sent_any or attempt == config.RETRIES:   # can't retry half a reply
                    raise ModelUnavailable(str(e))
                await asyncio.sleep(1)
        if last_err:
            raise ModelUnavailable(str(last_err))

    usage.cost_usd = estimate_cost(model, usage.input_tokens, usage.output_tokens)
    usage.seconds = round(time.time() - start, 2)
    _log(session_id, "chat", model, usage, "ok")


async def _fake_chat(history, audio):
    turns = sum(1 for m in history if m["role"] == "user") + (1 if audio else 0)
    moods = ["firm", "thinking", "firm", "pleased", "neutral"]
    offer = max(46, 52 - max(0, turns - 1) * 2)
    text = ""
    if audio:
        text += "Heard: I can offer forty riyals per kilo if we sign for six months.\n"
    text += (f"[mood: {moods[turns % len(moods)]}] [offer: {offer}]\n"
             f"I hear you. My price is {offer} riyals per kilo, and that reflects the quality. "
             f"What can you offer me in return?")
    for i in range(0, len(text), 12):            # stream in small pieces like the real thing
        await asyncio.sleep(0.01)
        yield text[i:i + 12]


# ---------------------------------------------------------------------------
# One-shot JSON (grading, drafting)
# ---------------------------------------------------------------------------
async def complete_json(task, system, user_text, session_id):
    model = config.MODELS[task]
    start = time.time()
    if fake_mode():
        data, tin, tout = _fake_json(task), 1200, 300
    else:
        last_err = None
        for attempt in range(config.RETRIES + 1):
            try:
                from google.genai import types
                resp = await _gemini().aio.models.generate_content(
                    model=model,
                    contents=[types.Content(role="user", parts=[types.Part(text=user_text)])],
                    config=_config(task, system, json_output=True, temperature=0.3))
                raw = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip()).strip()
                data = json.loads(raw)
                tin, tout = _usage_from(resp.usage_metadata)
                last_err = None
                break
            except Exception as e:
                last_err = e
                _log(session_id, task, model, Usage(seconds=round(time.time() - start, 2)),
                     f"error:{type(e).__name__}")
                if attempt < config.RETRIES:
                    await asyncio.sleep(1)
        if last_err:
            raise ModelUnavailable(str(last_err))
    usage = Usage(tin, tout, estimate_cost(model, tin, tout), round(time.time() - start, 2))
    _log(session_id, task, model, usage, "ok")
    return data, usage


def _fake_json(task):
    if task == "draft":
        return {"title": "Asking a landlord to lower rent", "summary": "Renegotiate an office lease.",
                "category": "negotiation", "difficulty": "medium",
                "brief": "You run a small design studio and want lower rent when your lease renews.",
                "goal": "Agree a lower rent or better terms by showing value as a tenant.",
                "character": {"name": "Faisal", "role": "Property Manager, Dunes Real Estate", "look": "man-glasses"},
                "opening": "Good to see you. I understand your lease is up for renewal soon.",
                "persona": "Practical and polite, but protective of the building's income.",
                "private_info": "Two other units in the building are empty.",
                "rubric": ["Prepared with market data", "Asked about the landlord's situation",
                           "Proposed creative terms", "Confirmed the agreement clearly"]}
    return {"overall_score": 6, "summary": "Test feedback: a reasonable start with room to improve.",
            "criteria": [{"name": "Opening", "score": 3, "comment": "Clear first offer."},
                         {"name": "Questions", "score": 2, "comment": "Few questions about their side."}],
            "strengths": ["Opened with a clear number"],
            "improvements": ["Ask what the other side needs before conceding"],
            "missed_opportunity": "Offering faster payment could have unlocked a lower price.",
            "outcome": {"reached": True, "value": 46, "description": "Agreed at QAR 46/kg on 30-day terms."}}


# ---------------------------------------------------------------------------
# Speech to text (fallback only: normally the chat model hears the audio directly)
# ---------------------------------------------------------------------------
async def transcribe(audio, mime, session_id):
    model = config.MODELS["chat"]
    start = time.time()
    if fake_mode():
        return "I can offer forty riyals per kilo if we sign for six months."
    from google.genai import types
    try:
        resp = await _gemini().aio.models.generate_content(
            model=model,
            contents=[types.Content(role="user", parts=[
                types.Part.from_bytes(data=audio, mime_type=mime),
                types.Part(text="Transcribe this recording exactly. It may be English or Arabic. "
                                "Return only the transcript, or an empty string if nothing is said.")])],
            config=_config("chat", temperature=0))
    except Exception as e:
        _log(session_id, "transcribe", model, Usage(seconds=round(time.time() - start, 2)),
             f"error:{type(e).__name__}")
        raise ModelUnavailable(str(e))
    tin, tout = _usage_from(resp.usage_metadata)
    _log(session_id, "transcribe", model,
         Usage(tin, tout, estimate_cost(model, tin, tout), round(time.time() - start, 2)), "ok")
    return (resp.text or "").strip().strip('"')


# ---------------------------------------------------------------------------
# Text to speech
# ---------------------------------------------------------------------------
async def speak(text, lang, gender, mood, session_id):
    """Returns (audio_bytes, mime, cost) or None if every provider fails."""
    if fake_mode():
        return _fake_speech(text), "audio/wav", 0.0
    for provider in config.TTS_PROVIDERS:
        model = config.GEMINI_TTS_MODEL if provider == "gemini" else "edge-tts"
        start = time.time()
        try:
            if provider == "edge":
                audio, mime = await _tts_edge(text, lang, gender)
            elif provider == "gemini":
                audio, mime = await _tts_gemini(text, gender, mood)
            else:
                continue
            # TTS doesn't report tokens like chat does, so estimate:
            # ~4 characters per input token, ~25 audio tokens per second, ~14 characters per second.
            tin, tout = len(text) // 4, int(len(text) / 14 * 25)
            usage = Usage(tin, tout, estimate_cost(model, tin, tout), round(time.time() - start, 2))
            _log(session_id, "speak", model, usage, "ok")
            return audio, mime, usage.cost_usd
        except Exception as e:
            _log(session_id, "speak", model, Usage(seconds=round(time.time() - start, 2)),
                 f"error:{type(e).__name__}")
    return None


async def _tts_edge(text, lang, gender):
    import edge_tts
    voice = config.VOICES["edge"][gender].get(lang, config.VOICES["edge"][gender]["en"])

    async def run():
        chunks = []
        async for part in edge_tts.Communicate(text, voice, rate="+5%").stream():
            if part["type"] == "audio":
                chunks.append(part["data"])
        return b"".join(chunks)

    audio = await asyncio.wait_for(run(), timeout=config.REQUEST_TIMEOUT_SECONDS)
    if not audio:
        raise RuntimeError("empty audio")
    return audio, "audio/mpeg"


async def _tts_gemini(text, gender, mood):
    style = config.VOICE_STYLES.get(mood, config.VOICE_STYLES["neutral"])
    result = await _gemini().aio.interactions.create(
        model=config.GEMINI_TTS_MODEL,
        input=[{"type": "user_input", "content": [{
            "type": "text", "text": text,
            "annotations": [{"type": "speech_metadata", "style": style}]}]}],
        response_format={"type": "audio"},
        generation_config={"speech_config": [{"voice": config.VOICES["gemini"][gender]}]},
    )
    data = result.output_audio.data
    audio = base64.b64decode(data) if isinstance(data, str) else data
    if not audio:
        raise RuntimeError("empty audio")
    return audio, "audio/wav"


def _fake_speech(text):
    """A hum with syllable-like pulses, so lip-sync can be tested without a voice service."""
    import io, math, struct, wave
    rate, seconds = 16000, min(5.0, max(1.0, len(text) / 16))
    frames = bytearray()
    for i in range(int(rate * seconds)):
        t = i / rate
        env = max(0.0, math.sin(2 * math.pi * 3.5 * t)) ** 2
        frames += struct.pack("<h", int(0.4 * env * math.sin(2 * math.pi * 160 * t) * 32767))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(frames))
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Logging: one CSV row per call (numbers only, never content)
# ---------------------------------------------------------------------------
CALLS_LOG = os.path.join(config.LOG_DIR, "model_calls.csv")
FIELDS = ["timestamp", "session_id", "task", "model", "status",
          "input_tokens", "output_tokens", "cost_usd", "seconds"]


def _log(session_id, task, model, usage, status):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    new = not os.path.exists(CALLS_LOG)
    with open(CALLS_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "session_id": session_id, "task": task, "model": model, "status": status,
                    "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                    "cost_usd": f"{usage.cost_usd:.6f}", "seconds": usage.seconds})
