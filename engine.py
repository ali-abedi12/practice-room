"""
The conversation engine: sessions, turns and grading.

Why a turn is fast:
1. Voice turns send the recording straight to the chat model, which writes down what
   it heard and replies in the same call (one round trip instead of two).
2. The reply is streamed. As soon as the first sentence is complete it is sent off to
   be voiced, while the model keeps writing the rest.
3. Audio comes back sentence by sentence, so the student hears the start of the reply
   before the end has been generated.
"""

import asyncio
import base64
import csv
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import config
import llm
import scenarios as sc

HEADER_RE = re.compile(r"^\s*((?:\[\s*(?:mood|offer)\s*:[^\]]*\]\s*)+)", re.IGNORECASE)
HEARD_RE = re.compile(r"^\s*heard\s*:\s*(.*)$", re.IGNORECASE)
SENTENCE_END_RE = re.compile(r"[.!?؟…]+[\"'”’)]*\s+")

HOLD_LINES = {   # used only if the model breaks its number rule twice in a row
    "en": "I'm sorry, I can't move on that. My position stays at {value:g} {unit}.",
    "ar": "عذرًا، لا أستطيع التحرّك في ذلك. يبقى عرضي {value:g} {unit}.",
}


def is_arabic(text):
    return bool(re.search(r"[؀-ۿ]", text or ""))


@dataclass
class Session:
    id: str
    scenario: sc.Scenario
    lang: str
    messages: list = field(default_factory=list)  # {"role", "content", "mood", "offer", "voice"}
    position: float | None = None                  # the character's current number, if any
    tokens: int = 0
    cost: float = 0.0
    started_logged: bool = False
    feedback: dict | None = None
    last_active: float = field(default_factory=time.time)
    busy: bool = False

    def student_turns(self):
        return sum(1 for m in self.messages if m["role"] == "user")

    def add(self, usage):
        self.tokens += usage.input_tokens + usage.output_tokens
        self.cost += usage.cost_usd


SESSIONS: dict[str, Session] = {}


def new_session(scenario, lang):
    cutoff = time.time() - config.SESSION_IDLE_MINUTES * 60
    for sid in [k for k, s in SESSIONS.items() if s.last_active < cutoff]:
        SESSIONS.pop(sid, None)
    s = Session(id=uuid.uuid4().hex[:12], scenario=scenario, lang=lang,
                position=scenario.offer.start if scenario.offer else None)
    SESSIONS[s.id] = s
    return s


def history_for_model(s: Session):
    """Put the tags back on the character's earlier replies so the model keeps using them."""
    out = []
    for m in s.messages:
        if m["role"] == "assistant":
            tags = f"[mood: {m.get('mood', 'neutral')}]"
            if m.get("offer") is not None:
                tags += f" [offer: {m['offer']:g}]"
            out.append({"role": "assistant", "content": f"{tags}\n{m['content']}"})
        else:
            out.append({"role": "user", "content": m["content"]})
    return out


async def opening_audio(s: Session):
    text = sc.pick(s.scenario.opening, s.lang)
    return await llm.speak(text, s.lang, s.scenario.character.gender, "neutral", s.id)


# ---------------------------------------------------------------------------
# One turn
# ---------------------------------------------------------------------------
async def run_turn(s: Session, text=None, audio=None, voice_on=True):
    """Async generator of events (dicts) for the browser. See README for the event list."""
    s.last_active = time.time()
    if not s.started_logged:
        log_event(s, "started")
        s.started_logged = True

    scenario = s.scenario
    system = sc.character_prompt(scenario)
    history = history_for_model(s)
    heard = None

    if text:
        history.append({"role": "user", "content": text})

    correction = None
    header = None
    body_iter = None
    for attempt in range(3):
        if attempt == 2:                      # broke the rule twice: say a fixed holding line
            lang = "ar" if is_arabic(heard or text or "") else "en"
            hold = HOLD_LINES[lang].format(value=s.position, unit=scenario.offer.unit)
            header = ("firm", s.position)
            body_iter = _one_chunk(hold)
            break

        usage = llm.Usage()
        use_audio = audio if (audio and heard is None) else None
        msgs = history if (text or heard is None) else history + [{"role": "user", "content": heard}]
        sys_prompt = system + (sc.AUDIO_TURN_NOTE if use_audio else "")
        if correction:
            sys_prompt += f"\n\nCORRECTION FOR THIS REPLY: {correction}"

        stream = llm.chat_stream(sys_prompt, msgs, s.id, audio=use_audio, usage=usage)
        got_heard, header, leftover = await _read_header(stream, expect_heard=bool(use_audio))
        if use_audio:
            heard = got_heard
            if heard is not None:
                yield {"type": "heard", "text": heard}

        mood, offer = header
        if scenario.offer:
            problem = sc.check_offer(scenario.offer, offer, s.position, s.student_turns() + 1)
            if problem:
                await stream.aclose()
                s.add(usage)
                correction = problem
                continue
        body_iter = _chain(leftover, stream, usage, s)
        break

    if audio and heard is None:
        # The model didn't write down what it heard; transcribe separately for the record.
        try:
            heard = await llm.transcribe(audio[0], audio[1], s.id)
        except llm.ModelUnavailable:
            heard = ""
        yield {"type": "heard", "text": heard}

    student_text = text if text else (heard or "")
    mood, offer = header
    msg_id = uuid.uuid4().hex[:10]
    yield {"type": "start", "id": msg_id, "mood": mood}

    # Stream the text; send each complete sentence to be voiced as soon as it's ready.
    full, pending, tts_tasks, seq, voice_failed = "", "", [], 0, False

    def launch(sentence):
        nonlocal seq
        sentence = sc.strip_tags(sentence).strip()
        if voice_on and sentence:
            lang = "ar" if is_arabic(sentence) else "en"
            tts_tasks.append((seq, asyncio.create_task(
                llm.speak(sentence, lang, scenario.character.gender, mood, s.id))))
            seq += 1

    async def drain(wait_all=False):
        nonlocal voice_failed
        out = []
        while tts_tasks and (wait_all or tts_tasks[0][1].done()):
            n, task = tts_tasks.pop(0)
            result = await task
            if result:
                audio_bytes, mime, cost = result
                s.cost += cost
                out.append({"type": "audio", "seq": n, "mime": mime,
                            "data": base64.b64encode(audio_bytes).decode()})
            elif not voice_failed:
                voice_failed = True
                out.append({"type": "voice_unavailable"})
        return out

    async for chunk in body_iter:
        clean = sc.strip_tags(chunk) if "[" in chunk else chunk
        full += clean
        pending += clean
        yield {"type": "delta", "text": clean}
        # cut off finished sentences
        while True:
            m = SENTENCE_END_RE.search(pending)
            if not m:
                # start voicing a long first sentence at a comma, to begin speaking sooner
                if seq == 0 and len(pending.split()) >= 9:
                    c = max(pending.rfind(","), pending.rfind("،"))
                    if c > 0 and len(pending[:c].split()) >= 6:
                        launch(pending[:c + 1])
                        pending = pending[c + 1:]
                        continue
                break
            launch(pending[:m.end()])
            pending = pending[m.end():]
        for ev in await drain():
            yield ev
    if pending.strip():
        launch(pending)
    for ev in await drain(wait_all=True):
        yield ev

    full = sc.strip_tags(full).strip()
    s.messages.append({"role": "user", "content": student_text or "…", "voice": bool(audio)})
    s.messages.append({"role": "assistant", "content": full, "mood": mood,
                       "offer": offer if scenario.offer else None, "id": msg_id})
    if scenario.offer and offer is not None:
        s.position = offer
    yield {"type": "done", "id": msg_id, "text": full, "mood": mood,
           "turns_left": config.MAX_STUDENT_TURNS - s.student_turns(),
           "tokens": s.tokens, "cost": round(s.cost, 6)}


async def _read_header(stream, expect_heard):
    """
    Read from the stream until the 'Heard:' line (voice turns) and the tag line are complete.
    Returns (heard_text_or_None, (mood, offer), leftover_text).
    """
    buf, heard, done_heard = "", None, not expect_heard
    async for chunk in stream:
        buf += chunk
        if not done_heard:
            if "\n" not in buf.lstrip():
                if len(buf) < 400:
                    continue
            first, _, rest = buf.lstrip().partition("\n")
            m = HEARD_RE.match(first)
            if m:
                heard, buf = m.group(1).strip(), rest
            done_heard = True
        stripped = buf.lstrip()
        if not stripped:
            continue
        if not stripped.startswith("["):
            return heard, ("neutral", None), buf          # no tags: treat it all as the reply
        m = HEADER_RE.match(buf)
        if m:
            rest = buf[m.end():]
            # complete when the line has ended, or real text follows on the same line
            if "\n" in buf[:m.end()] or (rest.strip() and not rest.lstrip().startswith("[")):
                return heard, sc.parse_tags(m.group(1)), rest.lstrip()
    m = HEADER_RE.match(buf)
    if m:
        return heard, sc.parse_tags(m.group(1)), buf[m.end():].lstrip()
    return heard, ("neutral", None), buf


async def _chain(leftover, stream, usage, s):
    if leftover:
        yield leftover
    async for chunk in stream:
        yield chunk
    s.add(usage)


async def _one_chunk(text):
    yield text


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------
async def grade(s: Session):
    lines = [f"{sc.pick(s.scenario.character.name, 'en')}: {sc.pick(s.scenario.opening, s.lang)}"]
    for m in s.messages:
        who = "Student" if m["role"] == "user" else sc.pick(s.scenario.character.name, "en")
        lines.append(f"{who}: {m['content']}")
    data, usage = await llm.complete_json("grade", sc.grader_prompt(s.scenario, s.lang),
                                          "TRANSCRIPT:\n" + "\n".join(lines), s.id)
    s.add(usage)
    outcome = data.get("outcome") or {}
    value = outcome.get("value")
    try:
        value = float(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
    data["numbers"] = sc.outcome_numbers(s.scenario.offer, value) if outcome.get("reached") else None
    data["reveal"] = sc.pick(s.scenario.reveal, s.lang)
    data["tokens"], data["cost"] = s.tokens, round(s.cost, 6)
    s.feedback = data
    log_event(s, "completed", data)
    return data


# ---------------------------------------------------------------------------
# Usage tracking (no content, just counts and scores)
# ---------------------------------------------------------------------------
EVENTS_LOG = os.path.join(config.LOG_DIR, "sessions.csv")
EVENT_FIELDS = ["timestamp", "session_id", "scenario_id", "event", "language",
                "student_turns", "voice_turns", "reached", "value", "score"]


def log_event(s: Session, event, feedback=None):
    os.makedirs(config.LOG_DIR, exist_ok=True)
    new = not os.path.exists(EVENTS_LOG)
    fb = feedback or {}
    with open(EVENTS_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "session_id": s.id, "scenario_id": s.scenario.id, "event": event,
                    "language": s.lang, "student_turns": s.student_turns(),
                    "voice_turns": sum(1 for m in s.messages if m.get("voice")),
                    "reached": (fb.get("outcome") or {}).get("reached", ""),
                    "value": (fb.get("outcome") or {}).get("value", "") or "",
                    "score": fb.get("overall_score", "")})
