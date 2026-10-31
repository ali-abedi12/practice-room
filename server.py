"""
Web server. Run with:  uvicorn server:app --reload
Then open http://localhost:8000
"""

import base64
import csv
import json
import os
from collections import defaultdict
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

import config
import engine
import llm
import scenarios as sc

app = FastAPI(title="Practice Room")
app.mount("/static", StaticFiles(directory="static"), name="static")

LANGS = ("en", "ar")


def _lang(lang):
    return lang if lang in LANGS else "en"


def _session(sid):
    s = engine.SESSIONS.get(sid)
    if not s:
        raise HTTPException(404, "session_expired")
    return s


@app.get("/")
def index():
    return FileResponse("static/index.html")


# ---------------------------------------------------------------------------
# Scenario library
# ---------------------------------------------------------------------------
@app.get("/api/scenarios")
def list_scenarios(lang: str = "en"):
    lang = _lang(lang)
    return [sc.public_view(s, lang) for s in sc.load_all()]


@app.get("/api/scenarios/{scenario_id}/source")
def scenario_source(scenario_id: str):
    """
    Full scenario, including hidden fields, for the builder.
    In a real deployment this would sit behind faculty sign-in, so students can't read it.
    """
    s = sc.get(scenario_id)
    if not s:
        raise HTTPException(404, "not_found")
    return s.model_dump()


def _validated(body: dict):
    try:
        return sc.Scenario(**body)
    except ValidationError as e:
        errors = [{"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
                  for err in e.errors()]
        raise HTTPException(422, {"errors": errors})


@app.post("/api/scenarios")
def create_scenario(body: dict):
    try:
        s = sc.save_custom(_validated(body))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": s.id}


@app.put("/api/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: dict):
    existing = sc.get(scenario_id)
    if not existing or existing.preset:
        raise HTTPException(403, "presets_are_read_only")
    s = _validated(body)
    s.created = existing.created
    sc.save_custom(s, scenario_id)
    return {"id": scenario_id}


@app.delete("/api/scenarios/{scenario_id}")
def delete_scenario(scenario_id: str):
    if not sc.delete_custom(scenario_id):
        raise HTTPException(404, "not_found")
    return {"ok": True}


class DraftRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000)
    lang: str = "en"


@app.post("/api/scenarios/draft")
async def draft_scenario(req: DraftRequest):
    """Faculty describe a scenario in a sentence or two; the AI fills in the form for them to edit."""
    language = "Arabic" if req.lang == "ar" else "English"
    try:
        data, _ = await llm.complete_json("draft", sc.DRAFT_PROMPT.replace("{language}", language),
                                          req.description, session_id="builder")
    except llm.ModelUnavailable:
        raise HTTPException(503, "model_error")
    return data


# ---------------------------------------------------------------------------
# Practice sessions
# ---------------------------------------------------------------------------
class StartRequest(BaseModel):
    scenario_id: str
    lang: str = "en"


@app.post("/api/sessions")
def start_session(req: StartRequest):
    s = sc.get(req.scenario_id)
    if not s:
        raise HTTPException(404, "not_found")
    session = engine.new_session(s, _lang(req.lang))
    return {"session_id": session.id, "scenario": sc.public_view(s, session.lang),
            "turns_left": config.MAX_STUDENT_TURNS}


@app.get("/api/sessions/{sid}/opening-audio")
async def opening_audio(sid: str):
    s = _session(sid)
    result = await engine.opening_audio(s)
    if not result:
        return {"audio": None}
    audio, mime, cost = result
    s.cost += cost
    return {"audio": base64.b64encode(audio).decode(), "mime": mime}


@app.post("/api/sessions/{sid}/turn")
async def turn(sid: str,
               text: Optional[str] = Form(None),
               voice_on: bool = Form(True),
               audio: Optional[UploadFile] = File(None)):
    s = _session(sid)
    if s.feedback is not None:
        raise HTTPException(409, "session_finished")
    if s.student_turns() >= config.MAX_STUDENT_TURNS:
        raise HTTPException(429, "turn_limit")
    if s.busy:
        raise HTTPException(409, "busy")

    text = (text or "").strip() or None
    audio_tuple = None
    if audio is not None:
        data = await audio.read()
        if len(data) > config.MAX_AUDIO_BYTES:
            raise HTTPException(413, "recording_too_long")
        if data:
            audio_tuple = (data, audio.content_type or "audio/wav")
    if not text and not audio_tuple:
        raise HTTPException(400, "empty")
    if text and len(text) > config.MAX_MESSAGE_CHARS:
        raise HTTPException(413, "message_too_long")

    async def events():
        s.busy = True
        try:
            async for ev in engine.run_turn(s, text=text, audio=audio_tuple, voice_on=voice_on):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except llm.ModelUnavailable:
            yield json.dumps({"type": "error", "key": "model_error", "restore": text or ""}) + "\n"
        finally:
            s.busy = False

    # NDJSON: one JSON event per line, read by the browser as it arrives.
    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/sessions/{sid}/end")
async def end_session(sid: str):
    s = _session(sid)
    if s.feedback is not None:
        return s.feedback
    if s.student_turns() == 0:
        raise HTTPException(400, "nothing_to_grade")
    try:
        return await engine.grade(s)
    except llm.ModelUnavailable:
        raise HTTPException(503, "model_error")


# ---------------------------------------------------------------------------
# Insights
# ---------------------------------------------------------------------------
def _rows(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


@app.get("/api/insights")
def insights(lang: str = "en"):
    lang = _lang(lang)
    events, calls = _rows(engine.EVENTS_LOG), _rows(llm.CALLS_LOG)
    titles = {s.id: sc.pick(s.title, lang) for s in sc.load_all()}

    per = defaultdict(lambda: {"started": 0, "completed": 0, "reached": 0, "scores": [], "voice_turns": 0,
                               "turns": 0})
    for e in events:
        p = per[e["scenario_id"]]
        if e["event"] == "started":
            p["started"] += 1
        elif e["event"] == "completed":
            p["completed"] += 1
            p["reached"] += str(e["reached"]).lower() == "true"
            p["turns"] += int(e["student_turns"] or 0)
            p["voice_turns"] += int(e["voice_turns"] or 0)
            try:
                p["scores"].append(float(e["score"]))
            except ValueError:
                pass

    by_scenario = []
    for sid, p in per.items():
        by_scenario.append({
            "scenario_id": sid, "title": titles.get(sid, sid),
            "started": p["started"], "completed": p["completed"],
            "reached_pct": round(100 * p["reached"] / p["completed"]) if p["completed"] else None,
            "avg_score": round(sum(p["scores"]) / len(p["scores"]), 1) if p["scores"] else None,
            "voice_pct": round(100 * p["voice_turns"] / p["turns"]) if p["turns"] else None,
        })
    by_scenario.sort(key=lambda r: -r["started"])

    ok = [c for c in calls if c["status"] == "ok"]
    chat_times = [float(c["seconds"]) for c in ok if c["task"] == "chat"]
    total_cost = sum(float(c["cost_usd"] or 0) for c in calls)
    completed = sum(p["completed"] for p in per.values())
    all_scores = [x for p in per.values() for x in p["scores"]]
    return {
        "sessions_started": sum(p["started"] for p in per.values()),
        "sessions_completed": completed,
        "avg_score": round(sum(all_scores) / len(all_scores), 1) if all_scores else None,
        "total_cost": round(total_cost, 4),
        "cost_per_session": round(total_cost / completed, 4) if completed else None,
        "avg_reply_seconds": round(sum(chat_times) / len(chat_times), 2) if chat_times else None,
        "error_rate_pct": round(100 * (len(calls) - len(ok)) / len(calls), 1) if calls else None,
        "score_distribution": [sum(1 for x in all_scores if round(x) == i) for i in range(1, 11)],
        "by_scenario": by_scenario,
    }


@app.get("/api/config")
def client_config():
    return {"max_message_chars": config.MAX_MESSAGE_CHARS, "max_turns": config.MAX_STUDENT_TURNS,
            "looks": list(sc.LOOKS), "categories": list(sc.CATEGORIES)}
